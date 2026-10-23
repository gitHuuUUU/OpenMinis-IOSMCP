// SPDX-License-Identifier: MIT
// MinisRe's small LLVM 19 IR-only protection passes.  These are address
// indirection, not a promise that a static/dynamic analyst cannot recover them.
// No injected runtime, symbol lookup, anti-debugging or platform API is used.
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/Compiler.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"

using namespace llvm;

namespace {
// A mutable table and volatile loads keep the extra memory indirection in the
// emitted program.  Do not mark these tables constant/unnamed_addr or replace
// the volatile loads with ordinary loads: that permits trivial folding.
GlobalVariable *makeTable(Module &M, StringRef Name,
                          ArrayRef<Constant *> Targets) {
  auto *Ptr = PointerType::getUnqual(M.getContext());
  auto *Ty = ArrayType::get(Ptr, Targets.size());
  auto *Table = new GlobalVariable(
      M, Ty, false, GlobalValue::PrivateLinkage,
      ConstantArray::get(Ty, Targets), Name);
  Table->setAlignment(M.getDataLayout().getABITypeAlign(Ptr));
  appendToCompilerUsed(M, {Table});
  return Table;
}

Value *loadTarget(GlobalVariable *Table, unsigned Index, Instruction *Before,
                  const Twine &Name) {
  IRBuilder<> B(Before);
  B.SetCurrentDebugLocation(Before->getDebugLoc());
  Value *Slot = B.CreateInBoundsGEP(
      Table->getValueType(), Table, {B.getInt32(0), B.getInt32(Index)},
      Name + ".slot");
  auto *Loaded = B.CreateLoad(B.getPtrTy(), Slot, Name);
  Loaded->setVolatile(true);
  Loaded->setAlignment(
      Table->getParent()->getDataLayout().getABITypeAlign(B.getPtrTy()));
  return Loaded;
}

bool processFunction(const Function &F) {
  return !F.isDeclaration() && !F.hasFnAttribute(Attribute::Naked);
}

class IndirectCallsPass : public PassInfoMixin<IndirectCallsPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    SmallVector<CallBase *, 32> Sites;
    SmallVector<Constant *, 16> Targets;
    DenseMap<Function *, unsigned> Indices;
    for (Function &F : M) {
      if (!processFunction(F))
        continue;
      for (Instruction &I : instructions(F)) {
        auto *Call = dyn_cast<CallBase>(&I);
        // Retain callbr's asm-goto semantics.  Intrinsics must remain direct;
        // do not reinterpret an already indirect/aliased/bitcast callee.
        if (!Call || isa<CallBrInst>(Call) || Call->isInlineAsm())
          continue;
        auto *Callee = dyn_cast<Function>(Call->getCalledOperand());
        if (!Callee || Callee->isIntrinsic() || Callee->getAddressSpace() != 0)
          continue;
        if (auto *OrdinaryCall = dyn_cast<CallInst>(Call))
          if (OrdinaryCall->isMustTailCall())
            continue;
        if (!Indices.count(Callee)) {
          Indices[Callee] = Targets.size();
          Targets.push_back(Callee);
        }
        Sites.push_back(Call);
      }
    }
    if (Sites.empty()) {
      errs() << "MinisProtection indcall: 0 eligible call sites\n";
      return PreservedAnalyses::all();
    }
    auto *Table = makeTable(M, "minis_indcall_targets", Targets);
    for (CallBase *Call : Sites) {
      auto *Callee = cast<Function>(Call->getCalledOperand());
      Value *Target = loadTarget(Table, Indices.lookup(Callee), Call,
                                 "minis.indcall.target");
      // Mutate the operand only.  Calling convention, attributes, operand
      // bundles, debug locations and invoke exception edges stay untouched.
      Call->setCalledOperand(Target);
    }
    errs() << "MinisProtection indcall: " << Sites.size() << " call sites, "
           << Targets.size() << " targets\n";
    return PreservedAnalyses::none();
  }
  static bool isRequired() { return true; }
};

bool eligibleGlobal(const GlobalVariable &G) {
  StringRef Name = G.getName();
  // Reserved sections are ABI/runtime metadata rather than ordinary user data.
  // Taking a TLS address in a static table is invalid; preserve it unchanged.
  return G.getAddressSpace() == 0 && !G.isThreadLocal() &&
         !G.hasAppendingLinkage() && !G.hasSection() &&
         !Name.starts_with("llvm.") && !Name.starts_with("OBJC") &&
         !Name.starts_with("_OBJC") && !Name.starts_with("__objc") &&
         !Name.starts_with("minis_indcall_targets") &&
         !Name.starts_with("minis_indgv_targets");
}

// Support direct pointers and constant GEP/cast trees only.  Alias/ifunc,
// blockaddress, aggregate constants and other special forms are not rewritten.
bool gatherGlobals(Value *V, SmallVectorImpl<GlobalVariable *> &Globals) {
  if (auto *G = dyn_cast<GlobalVariable>(V)) {
    if (!eligibleGlobal(*G))
      return false;
    Globals.push_back(G);
    return true;
  }
  auto *Expr = dyn_cast<ConstantExpr>(V);
  if (!Expr || (!Expr->isCast() &&
                Expr->getOpcode() != Instruction::GetElementPtr))
    return false;
  // GEP indices are constants.  A GEP or cast has exactly one address source.
  return gatherGlobals(Expr->getOperand(0), Globals);
}

struct DataSite {
  Instruction *Owner;
  unsigned Operand;
};

Value *materializePointer(Value *V, Instruction *Before, GlobalVariable *Table,
                          const DenseMap<GlobalVariable *, unsigned> &Indices) {
  if (auto *G = dyn_cast<GlobalVariable>(V))
    return loadTarget(Table, Indices.lookup(G), Before, "minis.indgv.target");
  auto *Expr = cast<ConstantExpr>(V);
  Instruction *Expanded = Expr->getAsInstruction();
  Expanded->setOperand(
      0, materializePointer(Expr->getOperand(0), Before, Table, Indices));
  Expanded->setDebugLoc(Before->getDebugLoc());
  Expanded->insertBefore(Before->getIterator());
  return Expanded;
}

class IndirectGlobalsPass : public PassInfoMixin<IndirectGlobalsPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    SmallVector<DataSite, 32> Sites;
    SmallVector<Constant *, 16> Targets;
    DenseMap<GlobalVariable *, unsigned> Indices;
    auto AddOperand = [&](Instruction &I, unsigned Operand) {
      Value *V = I.getOperand(Operand);
      if (!V->getType()->isPointerTy())
        return;
      SmallVector<GlobalVariable *, 2> Globals;
      if (!gatherGlobals(V, Globals))
        return;
      for (auto *G : Globals)
        if (!Indices.count(G)) {
          Indices[G] = Targets.size();
          Targets.push_back(G);
        }
      Sites.push_back({&I, Operand});
    };
    for (Function &F : M) {
      if (!processFunction(F))
        continue;
      for (Instruction &I : instructions(F)) {
        if (auto *Load = dyn_cast<LoadInst>(&I))
          AddOperand(I, Load->getPointerOperandIndex());
        else if (auto *Store = dyn_cast<StoreInst>(&I))
          AddOperand(I, Store->getPointerOperandIndex());
        else if (auto *GEP = dyn_cast<GetElementPtrInst>(&I))
          AddOperand(I, GEP->getPointerOperandIndex());
        else if (isa<AtomicRMWInst>(I) || isa<AtomicCmpXchgInst>(I))
          AddOperand(I, 0);
        else if (auto *Call = dyn_cast<CallBase>(&I)) {
          if (isa<CallBrInst>(Call) || Call->isInlineAsm())
            continue;
          if (auto *Callee = Call->getCalledFunction())
            if (Callee->isIntrinsic())
              continue;
          for (Use &Arg : Call->args())
            AddOperand(I, Arg.getOperandNo());
        }
      }
    }
    if (Sites.empty()) {
      errs() << "MinisProtection indgv: 0 eligible global accesses\n";
      return PreservedAnalyses::all();
    }
    auto *Table = makeTable(M, "minis_indgv_targets", Targets);
    for (const auto &Site : Sites) {
      Value *Old = Site.Owner->getOperand(Site.Operand);
      Site.Owner->setOperand(
          Site.Operand, materializePointer(Old, Site.Owner, Table, Indices));
    }
    errs() << "MinisProtection indgv: " << Sites.size() << " access sites, "
           << Targets.size() << " targets\n";
    return PreservedAnalyses::none();
  }
  static bool isRequired() { return true; }
};
} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "MinisProtection", "2.0",
          [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "minis-indcall") {
                    MPM.addPass(IndirectCallsPass());
                    return true;
                  }
                  if (Name == "minis-indgv") {
                    MPM.addPass(IndirectGlobalsPass());
                    return true;
                  }
                  return false;
                });
          }};
}
