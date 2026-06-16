/*! AtriaDash + AtriaBlock host bridge. Loaded inside the dashboard iframe.
 *  Communicates with the parent React app via postMessage. No imports.
 */
(function () {
  "use strict";

  var listeners = {
    theme: [],
    context: [],
    change: [],
    visibility: [],
    props: [],
  };
  var pending = {};   // requestId -> {resolve, reject}
  var nextId = 1;

  function uuid() {
    return "r-" + (nextId++) + "-" + Math.floor(Math.random() * 1e9).toString(36);
  }

  function fire(name, payload) {
    var arr = listeners[name];
    if (!arr) return;
    for (var i = 0; i < arr.length; i++) {
      try { arr[i](payload); } catch (e) { console.error(e); }
    }
  }

  function send(msg) {
    parent.postMessage(msg, "*");
  }

  window.addEventListener("message", function (ev) {
    var msg = ev.data || {};
    if (!msg || typeof msg.type !== "string") return;

    if (msg.type === "theme")      return fire("theme", msg.tokens || {});
    if (msg.type === "context")    return fire("context", {
      sessionId: msg.sessionId, moduleName: msg.moduleName, moduleRoot: msg.moduleRoot,
    });
    if (msg.type === "change")     return fire("change", msg.paths || []);
    if (msg.type === "visibility") return fire("visibility", !!msg.visible);
    if (msg.type === "props")      return fire("props", msg.props || {});

    if (msg.type === "run:result") {
      var p = pending[msg.requestId];
      if (!p) return;
      delete pending[msg.requestId];
      p.resolve({
        exit_code: msg.exit_code,
        stdout: msg.stdout || "",
        stderr: msg.stderr || "",
        duration_ms: msg.duration_ms || 0,
      });
    }
    if (msg.type === "run:error") {
      var pe = pending[msg.requestId];
      if (!pe) return;
      delete pending[msg.requestId];
      var err = new Error(msg.message || msg.kind || "run failed");
      err.kind = msg.kind || "unknown";
      pe.reject(err);
    }
  });

  function onify(name) {
    return function (fn) { if (typeof fn === "function") listeners[name].push(fn); };
  }

  var AtriaDash = {
    onTheme:      onify("theme"),
    onContext:    onify("context"),
    onChange:     onify("change"),
    onVisibility: onify("visibility"),

    ready: function () { send({ type: "ready" }); },

    run: function (script, args, opts) {
      var requestId = uuid();
      var msg = {
        type: "run", requestId: requestId,
        script: script, args: args || [],
      };
      if (opts) {
        if (opts.stdin != null) msg.stdin = String(opts.stdin);
        if (opts.timeout_ms) msg.timeout_ms = opts.timeout_ms | 0;
      }
      return new Promise(function (resolve, reject) {
        pending[requestId] = { resolve: resolve, reject: reject };
        send(msg);
      });
    },

    json: function (script, args, opts) {
      return AtriaDash.run(script, args, opts).then(function (res) {
        if (res.exit_code !== 0) {
          var e = new Error("non-zero exit (" + res.exit_code + "): " + (res.stderr || ""));
          e.kind = "non-zero"; e.result = res;
          throw e;
        }
        try { return JSON.parse(res.stdout); }
        catch (parseErr) {
          var e2 = new Error("stdout is not valid JSON: " + parseErr.message);
          e2.kind = "bad-json"; e2.result = res;
          throw e2;
        }
      });
    },

    setBadge: function (value) { send({ type: "badge", value: value || null }); },
    setTitle: function (text)  { send({ type: "title", text: String(text || "") }); },
    toast:    function (opts)  { send({ type: "toast",
                                        message: String((opts && opts.message) || ""),
                                        severity: (opts && opts.severity) || "info" }); },
    openBlock: function (block, props) {
      send({ type: "openBlock", block: String(block || ""), props: props || {} });
    },
    openChat: function () { send({ type: "openChat" }); },

    resize: function (height) { send({ type: "resize", height: height | 0 }); },
  };

  // ── AtriaBlock (for push_block iframes) ──────────────────────────────────
  // Same wire protocol; thin alias so existing block HTML keeps working.
  var AtriaBlock = {
    onTheme:  AtriaDash.onTheme,
    onProps:  onify("props"),
    ready:    AtriaDash.ready,
    resize:   AtriaDash.resize,
    // Inject a free-text user message into the chat. This is the ONLY
    // outbound channel for blocks: server-side interactions happen through
    // the agent, not through typed RPCs. Keeping the payload as natural
    // language keeps blocks language-/runtime-agnostic.
    sendMessage: function (text) {
      send({ type: "chat", text: String(text == null ? "" : text) });
    },
  };

  window.AtriaDash = AtriaDash;
  window.AtriaBlock = AtriaBlock;
})();
