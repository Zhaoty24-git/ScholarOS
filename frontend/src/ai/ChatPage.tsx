import { useEffect, useState, useSyncExternalStore } from "react";
import { ChatController, MODEL, PROVIDERS, DEFAULT_PROVIDER, safeError, type AiTransport, type Provider, type ContextAttachment } from "./model";
import { Markdown } from "./Markdown";
import "./styles.css";
export function ChatPage({ controller, transport, contexts }: { controller: ChatController; transport: AiTransport; contexts: ContextAttachment[] }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const [question, setQuestion] = useState("");
  const [key, setKey] = useState("");
  const [persist, setPersist] = useState(true);
  const [provider, setProvider] = useState<Provider>(DEFAULT_PROVIDER);
  const [configuration, setConfiguration] = useState(false);
  const [contextIndex, setContextIndex] = useState("");
  const [stream, setStream] = useState(false);
  const [configError, setConfigError] = useState("");
  const [saving, setSaving] = useState(false);
  const current = state.sessions.find(s => s.id === state.selected)!;
  useEffect(() => {
    let disposed = false, remove: (() => void) | undefined;
    void controller.refresh();
    void transport.chunks((id,text) => controller.chunk(id,text)).then(close => { if (disposed) close(); else remove = close; });
    return () => { disposed = true; remove?.(); controller.cancel(); };
  }, [controller, transport]);
  return <section className="ai-page" aria-label="Agnes AI 助手">
    <div className="ai-model"><span className="ai-spark" aria-hidden="true">✦</span><div><strong>Agnes 学习助手</strong><small>{MODEL} · {PROVIDERS[state.status.provider].label}</small></div><button onClick={() => { setKey(""); setConfigError(""); setProvider(state.status.configured ? state.status.provider : DEFAULT_PROVIDER); setConfiguration(v => !v); }}>API 配置</button></div>
    <aside className="demo-note ai-privacy">AI 需要网络。提交的问题、当前会话历史和你主动选择的上下文会发送到选定 Agnes 服务，可能产生费用或消耗配额。不会默认上传全部课程资料。应用不在 Codex 或自建云端保存会话；服务商的数据政策以你的账号条款为准。</aside>
    <label className="ai-check"><input type="checkbox" checked={state.consent} onChange={e => controller.consent(e.target.checked)} />我已了解数据发送范围与可能费用，同意主动提交时联网</label>
    {!state.status.available && <p role="status" className="ai-help">浏览器预览不开放真实 API 调用，请在 Android APK 中配置密钥。</p>}
    {(configuration || !state.status.configured) && <form className="panel ai-config" data-testid="ai-config" onSubmit={async e => {
      e.preventDefault(); if (saving) return; setSaving(true); setConfigError("");
      const value = key; setKey("");
      try { await controller.configure(value, persist, provider); setConfiguration(false); setContextIndex(""); }
      catch (error) { setConfigError(safeError(error)); }
      finally { setSaving(false); }
    }}>
      <h2>Agnes API 配置</h2>
      <label htmlFor="ai-provider">密钥所属账号区域</label><select id="ai-provider" value={provider} onChange={e => { setProvider(e.target.value as Provider); setKey(""); }}>
        <option value="agnes-cn">国内站（默认）</option><option value="agnes-international">国际站</option>
      </select><p className="ai-endpoint">{PROVIDERS[provider].baseUrl}</p>
      <label htmlFor="ai-key">新的 API Key（仅在手机输入）</label><input id="ai-key" type="password" value={key} onChange={e => setKey(e.target.value)} autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={4096} required />
      <label className="ai-check"><input type="checkbox" checked={persist} onChange={e => setPersist(e.target.checked)} />使用 Android Keystore 加密保存</label>
      <p className="ai-help">关闭后只在原生内存保留，退出或重启需重新输入。安全存储失败不会降级为明文。更换密钥会取消请求并清空会话。</p>
      <button className="primary" type="submit" disabled={saving || !state.status.available || !state.consent || !PROVIDERS[provider].baseUrl}>{saving ? "保存中…" : "保存并启用"}</button>
      {configError && <p role="alert">{configError}</p>}
    </form>}
    {state.status.configured && <div className="ai-key-status"><span>密钥已配置 · {state.status.persistent ? "Keystore 加密保存" : "仅原生内存"}（不显示密钥）</span><button onClick={() => { setKey(""); setContextIndex(""); void controller.removeKey(); }}>删除密钥</button></div>}
    <div className="ai-session-tools"><label htmlFor="ai-session">当前会话</label><select id="ai-session" value={state.selected} onChange={e => { controller.select(e.target.value); setQuestion(""); setContextIndex(""); }}>{state.sessions.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select><button onClick={() => { controller.newSession(); setQuestion(""); setContextIndex(""); }}>新建会话</button><button onClick={() => { controller.clearSession(); setQuestion(""); setContextIndex(""); }}>清除会话</button></div>
    <div className="ai-messages" aria-live="polite" aria-busy={state.pending}>
      {current.visible.length === 0 && <div className="ai-empty"><h2>从一个问题开始</h2><p>例如：解释牛顿—拉夫逊潮流计算的思路。</p><p>本页回复由 AI 生成，请核对公式与结论。资料解析、检索与 RAG 尚未实现，不提供虚构文件引用。</p></div>}
      {current.visible.map((message,i) => <article className={"ai-message ai-"+message.role} key={i}><div className="ai-message-source">{message.role === "user" ? "用户提供的问题" : "AI 生成 · 请核对"}{message.state === "pending" ? " · 生成中" : message.state === "incomplete" ? " · 未完成" : ""}</div>{message.context && <p className="ai-context-label">主动附加：{message.context}（合成演示数据）</p>}<Markdown text={message.text || (message.state === "pending" ? "正在等待回复…" : "此请求未完成。")} /></article>)}
    </div>
    {state.error && <p role="alert" className="ai-error">{state.error}</p>}
    <form className="panel ai-composer" onSubmit={e => { e.preventDefault(); const text = question; const context = contextIndex === "" ? null : contexts[Number(contextIndex)]; void controller.send(text, context, stream).then(sent => { if (sent) setQuestion(""); }); }}>
      <label htmlFor="ai-context">主动附加本地信息</label><select id="ai-context" value={contextIndex} onChange={e => setContextIndex(e.target.value)}><option value="">不附加课程或作业（默认）</option>{contexts.map((c,i) => <option value={i} key={i}>合成演示 · {c.label}</option>)}</select>
      {contextIndex !== "" && <details className="ai-context-preview"><summary>将发送的合成上下文（点击核对）</summary><pre>{contexts[Number(contextIndex)].text}</pre></details>}
      <p className="ai-help">已发送的上下文会留在当前会话历史中；新建会话可清除。较早或过长的对话可能不再发送。不会自动读取任何文件。</p>
      <label htmlFor="ai-question">你的问题</label><textarea id="ai-question" rows={3} maxLength={6000} value={question} disabled={state.pending} onChange={e => setQuestion(e.target.value)} placeholder="输入问题，或说明你希望如何理解这道题…" />
      <div className="ai-send"><label className="ai-check"><input type="checkbox" checked={stream} onChange={e => setStream(e.target.checked)} />流式回复（可选）</label>{state.pending ? <button type="button" className="secondary" onClick={() => controller.cancel()}>取消请求</button> : <button type="submit" className="primary" disabled={!question.trim() || !state.status.configured || !state.consent}>发送</button>}</div>
    </form>
  </section>;
}
