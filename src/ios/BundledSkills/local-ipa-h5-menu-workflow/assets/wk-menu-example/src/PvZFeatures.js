/* PvZ menu v2: the actual Cocos H5 battle, not the native fallback game. */
(function () {
  'use strict';
  var w = window;
  if (w.__PVZMenuH5 && w.__PVZMenuH5.version === 2) return;
  var state = { kill: false, rapid: false, seq: 0 };
  var frameId = 'pvz-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  var hooks = {}, ready = false, diagnostic = '等待 Cocos 战斗脚本';
  var phases = new WeakMap();
  var counters = { killHits: 0, confirmedZeroHp: 0, pendingZeroHp: 0, rapidCalls: 0 };
  var constants = null;
  var commandKind = 'pvz-menu-v2-state';

  function number(value, fallback) {
    var result = Number(value);
    return isFinite(result) ? result : fallback;
  }

  function ownHero(npc) {
    return !!npc && Number(npc.camp) === Number(constants.PLAYER_CAMP.myPlayer) &&
      typeof npc.isHero === 'function' && npc.isHero() === true;
  }

  function enemyCamp(camp) {
    return Number(camp) === Number(constants.PLAYER_CAMP.opponents) ||
      Number(camp) === Number(constants.PLAYER_CAMP.opponentsCoop);
  }

  function postStatus() {
    var text = diagnostic;
    if (ready) {
      text = 'Cocos 战斗已连接 · 秒杀命中 ' + counters.killHits + ' · 攻速 ' +
        (state.rapid ? '16×' : '原速');
      if (counters.pendingZeroHp) text += ' · 待服务端确认 ' + counters.pendingZeroHp;
    }
    var message = {
      version: 2, ready: ready, diagnostic: text, frameId: frameId,
      hookCount: Object.keys(hooks).length, kill: state.kill, rapid: state.rapid,
      seq: state.seq, counters: counters
    };
    try {
      if (w.webkit && w.webkit.messageHandlers && w.webkit.messageHandlers.pvzMenuStatus)
        w.webkit.messageHandlers.pvzMenuStatus.postMessage(message);
    } catch (ignore) {}
  }

  function propagate() {
    var message = { kind: commandKind, version: 2, kill: state.kill, rapid: state.rapid, seq: state.seq };
    for (var i = 0; i < w.frames.length; i++) {
      try { w.frames[i].postMessage(message, '*'); } catch (ignore) {}
    }
  }

  w.__PVZMenuSetState = function (next) {
    if (!next || !isFinite(Number(next.seq)) || Number(next.seq) < state.seq) return;
    state.kill = next.kill === true;
    state.rapid = next.rapid === true;
    state.seq = Number(next.seq);
    propagate();
    postStatus();
  };
  w.addEventListener('message', function (event) {
    var message = event.data;
    if (message && message.kind === commandKind && message.version === 2)
      w.__PVZMenuSetState(message);
  }, false);

  function exportedClass(module) {
    return module && typeof module.default === 'function' ? module.default : module;
  }

  function wrap(proto, name, make) {
    var original = proto[name];
    if (typeof original !== 'function') throw new Error('缺少方法 ' + name);
    if (original.__pvzV2) { hooks[name] = original; return; }
    var replacement = make(original);
    Object.defineProperty(replacement, '__pvzV2', { value: true });
    Object.defineProperty(replacement, '__pvzOriginal', { value: original });
    proto[name] = replacement;
    if (proto[name] !== replacement) throw new Error('方法不可写 ' + name);
    hooks[name] = replacement;
  }

  function install() {
    if (!w.cc || typeof w.__require !== 'function') return;
    try {
      var combat = exportedClass(w.__require('CombatObj'));
      var skill = exportedClass(w.__require('Skill'));
      constants = w.__require('ConstValue');
      if (!combat || !combat.prototype || !skill || !skill.prototype ||
          !constants || !constants.PLAYER_CAMP || Number(constants.PLAYER_CAMP.myPlayer) !== 1 ||
          typeof combat.prototype.chgHp !== 'function' ||
          typeof combat.prototype.recvDamage !== 'function' ||
          typeof skill.prototype.getCD !== 'function' || typeof skill.prototype.update !== 'function') {
        ready = false;
        diagnostic = '游戏脚本版本不匹配：缺少 CombatObj / Skill 接口';
        return;
      }
      if (ready && combat.prototype.chgHp === hooks.chgHp &&
          skill.prototype.getCD === hooks.getCD && skill.prototype.update === hooks.update) return;
      ready = false;

      // Exact health mutation gateway, after armor/damage formulas. Healing,
      // friendly targets, enemy attacks and reflected damage remain unchanged.
      wrap(combat.prototype, 'chgHp', function (original) {
        return function (delta, attackerCamp) {
          if (!state.kill || !(number(delta, 0) < 0) || !enemyCamp(this.camp) ||
              Number(attackerCamp) !== Number(constants.PLAYER_CAMP.myPlayer))
            return original.apply(this, arguments);
          var hp = Math.max(number(this.hp, 0), number(this.tmpHp, 0), number(this.maxHp, 0), 1);
          var args = Array.prototype.slice.call(arguments);
          args[0] = -Math.min(Number.MAX_SAFE_INTEGER, Math.max(Math.abs(number(delta, 0)), Math.ceil(hp * 2)));
          var ownLimit = Object.prototype.hasOwnProperty.call(this, 'bBreakDropHpLimit');
          var previousLimit = this.bBreakDropHpLimit;
          this.bBreakDropHpLimit = true;
          counters.killHits++;
          try {
            var result = original.apply(this, args);
            if (number(this.hp, 1) <= 0) counters.confirmedZeroHp++;
            else if (number(this.tmpHp, 1) <= 0) counters.pendingZeroHp++;
            return result;
          } finally {
            if (ownLimit) this.bBreakDropHpLimit = previousLimit;
            else delete this.bBreakDropHpLimit;
          }
        };
      });

      // The real Skill cooldown is in milliseconds. Do not change game dt,
      // movement, enemy cooldowns or player attributes/SafeNumber storage.
      wrap(skill.prototype, 'getCD', function (original) {
        return function () {
          var value = original.apply(this, arguments);
          if (state.rapid && ownHero(this.pBindNpcObj) && typeof value === 'number' && isFinite(value) && value > 0) {
            counters.rapidCalls++;
            // A just-initialized skill gets its first deltaTime from this
            // getter. Remember that phase so update does not divide it twice.
            if (!phases.has(this) && !(this.deltaTime > 0)) phases.set(this, 16);
            return Math.min(value, Math.max(16, value / 16));
          }
          return value;
        };
      });

      // Convert the remaining cooldown once at each ON/OFF transition. The
      // original update still runs once with the original dt and return value.
      wrap(skill.prototype, 'update', function (original) {
        return function () {
          var factor = state.rapid && ownHero(this.pBindNpcObj) ? 16 : 1;
          var previous = phases.has(this) ? phases.get(this) : 1;
          if (factor !== previous && typeof this.deltaTime === 'number' && isFinite(this.deltaTime) && this.deltaTime > 0)
            this.deltaTime = this.deltaTime * previous / factor;
          phases.set(this, factor);
          return original.apply(this, arguments);
        };
      });
      ready = true;
      diagnostic = 'Cocos 战斗接口已安装';
    } catch (error) {
      ready = false;
      diagnostic = '等待战斗模块：' + String(error && error.message ? error.message : error).slice(0, 120);
    }
  }

  w.__PVZMenuH5 = {
    version: 2,
    status: function () {
      return { ready: ready, diagnostic: diagnostic, hookCount: Object.keys(hooks).length,
        kill: state.kill, rapid: state.rapid, seq: state.seq,
        killHits: counters.killHits, confirmedZeroHp: counters.confirmedZeroHp,
        pendingZeroHp: counters.pendingZeroHp, rapidCalls: counters.rapidCalls };
    }
  };
  install();
  postStatus();
  w.setInterval(function () { install(); postStatus(); }, 1000);
}());
