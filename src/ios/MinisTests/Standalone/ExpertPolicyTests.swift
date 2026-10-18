import Foundation

@main struct ExpertPolicyTests {
    static func main() throws {
        var count=0
        func check(_ ok: Bool,_ label: String) { precondition(ok,label);count += 1 }
        var p=ExpertProfile()
        check(p.allowsTool("file_read"),"empty inherits")
        p.allowedTools=["file_read","file_write"];p.deniedTools=["file_write"]
        check(p.allowsTool("file_read"),"whitelist permits")
        check(!p.allowsTool("shell_execute"),"whitelist restricts")
        check(!p.allowsTool("file_write"),"blacklist precedence")
        p.defaultMode="plan";check(!p.allowsTool("file_read"),"plan has no tools")
        p.defaultMode="review";check(p.allowsTool("file_read"),"review obeys tool policy")
        check(p.isAvailable(in:nil),"global visible")
        p.workspaceID="project-one"
        check(p.isAvailable(in:"project-one"),"matching workspace")
        check(!p.isAvailable(in:"project-two"),"other workspace hidden")
        check(!p.isAvailable(in:nil),"global unknown not workspace")
        p.injectFullRules=true;p.injectBaseline=true;p.allowedTools=["file_read","file_read",""]
        p.normalize()
        check(!p.injectBaseline && p.injectFullRules,"rules mutually exclusive")
        check(p.allowedTools == ["file_read"],"normalize tool duplicates")
        let roundtrip=try JSONDecoder().decode(ExpertProfile.self,from:JSONEncoder().encode(p))
        check(roundtrip == p,"all settings persist")
        p.defaultMode="bad";p.category="bad";p.normalize()
        check(p.defaultMode == "inherit" && p.category == "开发","invalid defaults clamp")
        let snippets=[PromptFragment(title:"first",body:"same"),PromptFragment(title:"duplicate",body:" same \n"),PromptFragment(title:"disabled",body:"not-sent",enabled:false),PromptFragment(title:"last",body:"last")]
        check(PromptComposition.compose(base:"base",includeBuiltIn:true,fragments:snippets)=="base\n\nsame\n\nlast","ordered exact dedup")
        check(PromptComposition.compose(base:"base",includeBuiltIn:false,fragments:snippets)=="same\n\nlast","custom only")
        check(PromptComposition.compose(base:"same",includeBuiltIn:true,fragments:snippets)=="same\n\nlast","dedup against builtin")
        check(PromptComposition.compose(base:"",includeBuiltIn:false,fragments:[]) == "","empty no fake injection")
        let long=[PromptFragment(title:"bounded",body:String(repeating:"x",count:17000))]
        check(PromptComposition.compose(base:"",includeBuiltIn:false,fragments:long).count == 16000,"bounded fragment")
        print("Expert policy: \(count) production checks passed")
    }
}
