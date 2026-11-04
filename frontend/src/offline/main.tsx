import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { App as NativeApp } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import {
  courses,
  makeDemo,
  navigation,
  deadlineState,
  formatDeadline,
  safeRoute,
  VERSION,
  type Assignment,
} from "./model";
import "./styles.css";

const demo = makeDemo();
const course = (id: string) => courses.find((c) => c.id === id)!;
const icons = [
  "M3 10 12 3l9 7v10H6V10",
  "M4 4h7v16H4zM13 4h7v16h-7",
  "m5 7 2 2 4-4M13 7h7M5 15l2 2 4-4M13 15h7",
  "M5 17h14l-2-3V9a5 5 0 0 0-10 0v5ZM10 21h4",
  "M3 6h7l2 3h9v11H3Z",
  "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
];
function Icon({ index }: { index: number }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={icons[index]} />
    </svg>
  );
}
function navigate(path: string) {
  window.location.hash = path;
}
function back() {
  if (window.history.length > 1 && safeRoute(window.location.hash) !== "home")
    window.history.back();
  else if (safeRoute(window.location.hash) !== "home")
    window.location.replace("#home");
  else if (Capacitor.isNativePlatform()) void NativeApp.exitApp();
}
function Task({ task }: { task: Assignment }) {
  const state = deadlineState(task.deadline);
  return (
    <button
      className="list-row task-row"
      onClick={() => navigate("assignments/" + task.id)}
      data-testid={"task-" + task.id}
    >
      <span
        className={"task-dot " + (task.submitted ? "done" : state.kind)}
        aria-hidden="true"
      >
        {task.submitted ? "✓" : ""}
      </span>
      <span className="row-copy">
        <span className="row-title">{task.title}</span>
        <span className="meta">
          {course(task.courseId).name} · {formatDeadline(task.deadline)}
        </span>
        <span className={"tag " + (task.submitted ? "done" : state.kind)}>
          {task.submitted ? "已提交（演示）" : state.label}
        </span>
      </span>
      <span aria-hidden="true">›</span>
    </button>
  );
}
export function OfflineApp() {
  const [route, setRoute] = useState(() => safeRoute(window.location.hash));
  const [limit, setLimit] = useState(8);
  const [theme, setTheme] = useState("system");
  useEffect(() => {
    const changed = () => {
      setRoute(safeRoute(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", changed);
    let disposed = false;
    let remove: (() => Promise<void>) | undefined;
    if (Capacitor.isNativePlatform())
      void NativeApp.addListener("backButton", back).then((listener) => {
        if (disposed) void listener.remove();
        else remove = () => listener.remove();
      });
    return () => {
      disposed = true;
      window.removeEventListener("hashchange", changed);
      void remove?.();
    };
  }, []);
  const [page, id] = route.split("/");
  const today = demo.assignments.filter(
    (t) => !t.submitted && deadlineState(t.deadline).kind === "today",
  ).length;
  const title = navigation.find((n) => n[0] === page)?.[1] || "首页";
  const task = demo.assignments.find((t) => t.id === id);
  const notice = demo.notices.find((n) => n.id === id);
  const selectedCourse = courses.find((c) => c.id === id);
  const section = (label: string, destination: string) => (
    <div className="section-heading">
      <h2>{label}</h2>
      <button onClick={() => navigate(destination)}>
        查看全部 <span aria-hidden="true">↗</span>
      </button>
    </div>
  );
  return (
    <div className={"offline-app theme-" + theme}>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <span>
            ScholarOS<small>你的学习工作台</small>
          </span>
        </div>
        <span className="mode">
          <i />
          离线演示模式
        </span>
      </header>
      <main id="content" key={route}>
        {id && (
          <button className="back" onClick={back}>
            ← 返回{title}列表
          </button>
        )}
        {!id && page === "home" && (
          <>
            <div className="eyebrow">LEARNING, AT YOUR PACE</div>
            <h1>让学习，井然有序。</h1>
            <p className="subtitle">课程、作业与通知，在这里轻松掌握。</p>
            <section className="overview">
              <div>
                <span className="overline">今日待办 · 合成数据</span>
                <div className="big-number">
                  {today}
                  <span>项作业今天截止</span>
                </div>
                <p>从一件小事开始，找回自己的学习节奏。</p>
                <button
                  className="primary"
                  onClick={() => navigate("assignments")}
                >
                  查看我的作业 <span aria-hidden="true">→</span>
                </button>
              </div>
              <span className="orbit" aria-hidden="true">
                <span>学</span>
              </span>
            </section>
            <div className="demo-note">
              <span aria-hidden="true">◇</span>{" "}
              所有内容均为合成演示数据。无需登录，不会同步或上传。
            </div>
            {section("最近作业", "assignments")}
            <section className="panel">
              {demo.assignments.slice(0, 3).map((t) => (
                <Task key={t.id} task={t} />
              ))}
            </section>
            {section("我的课程", "courses")}
            <div className="course-grid">
              {courses.map((c, i) => (
                <button
                  key={c.id}
                  className={"course-card " + c.color}
                  onClick={() => navigate("courses/" + c.id)}
                >
                  <span className="course-code">
                    {c.code}
                    <span>0{i + 1}</span>
                  </span>
                  <h3>{c.name}</h3>
                  <span>
                    {c.teacher} <span aria-hidden="true">↗</span>
                  </span>
                </button>
              ))}
            </div>
            {section("最近通知", "notices")}
            <section className="panel">
              {demo.notices.slice(0, 2).map((n) => (
                <button
                  className="list-row"
                  key={n.id}
                  onClick={() => navigate("notices/" + n.id)}
                >
                  <span className="notice-icon" aria-hidden="true">
                    ◷
                  </span>
                  <span className="row-copy">
                    <span className="row-title">{n.title}</span>
                    <span className="meta">
                      {course(n.courseId).name} · {n.date}
                    </span>
                  </span>
                  <span aria-hidden="true">›</span>
                </button>
              ))}
            </section>
          </>
        )}
        {!id && page !== "home" && (
          <div className="page-heading">
            <span className="eyebrow">SCHOLAROS / OFFLINE</span>
            <h1>{title}</h1>
            <p className="subtitle">合成数据 · 仅供离线体验</p>
          </div>
        )}
        {page === "courses" &&
          (!id ? (
            <div className="course-grid">
              {courses.map((c) => (
                <button
                  key={c.id}
                  className={"course-card " + c.color}
                  onClick={() => navigate("courses/" + c.id)}
                >
                  <span className="course-code">{c.code}</span>
                  <h3>{c.name}</h3>
                  <span>{c.teacher} · 查看课程 →</span>
                </button>
              ))}
            </div>
          ) : selectedCourse ? (
            <article className="detail">
              <span className="eyebrow">{selectedCourse.code} · 合成课程</span>
              <h1>{selectedCourse.name}</h1>
              <p className="meta">{selectedCourse.teacher}</p>
              <p>{selectedCourse.description}</p>
              <h2>课程作业</h2>
              <section className="panel">
                {demo.assignments
                  .filter((t) => t.courseId === id)
                  .slice(0, 4)
                  .map((t) => (
                    <Task key={t.id} task={t} />
                  ))}
              </section>
            </article>
          ) : (
            <p role="alert">未找到该演示课程。</p>
          ))}
        {page === "assignments" &&
          (!id ? (
            <>
              <section className="panel">
                {demo.assignments.slice(0, limit).map((t) => (
                  <Task key={t.id} task={t} />
                ))}
              </section>
              <p className="list-count">
                显示 {Math.min(limit, demo.assignments.length)} /{" "}
                {demo.assignments.length} 项合成作业
              </p>
              {limit < demo.assignments.length && (
                <button
                  className="secondary load-more"
                  onClick={() => setLimit((n) => n + 8)}
                >
                  加载更多作业
                </button>
              )}
            </>
          ) : task ? (
            <article className="detail">
              <span className="eyebrow">作业详情 · 合成数据</span>
              <h1>{task.title}</h1>
              <p>{course(task.courseId).name}</p>
              <dl>
                <dt>截止日期</dt>
                <dd>{formatDeadline(task.deadline)}</dd>
                <dt>提交状态</dt>
                <dd>{task.submitted ? "已提交（演示）" : "未提交（演示）"}</dd>
                <dt>截止提醒</dt>
                <dd>
                  {task.submitted
                    ? "已完成（演示）"
                    : deadlineState(task.deadline).label}
                </dd>
              </dl>
              <h2>作业说明</h2>
              <p className="body-text">{task.body}</p>
              <aside className="demo-note">
                离线演示不支持真实提交、上传或批改。
              </aside>
            </article>
          ) : (
            <p role="alert">未找到该演示作业。</p>
          ))}
        {page === "notices" &&
          (!id ? (
            <section className="panel">
              {demo.notices.map((n) => (
                <button
                  className="list-row"
                  key={n.id}
                  onClick={() => navigate("notices/" + n.id)}
                >
                  <span className="notice-icon" aria-hidden="true">
                    ◷
                  </span>
                  <span className="row-copy">
                    <span className="row-title">{n.title}</span>
                    <span className="meta">
                      {course(n.courseId).name} · {n.date}
                    </span>
                  </span>
                  <span aria-hidden="true">›</span>
                </button>
              ))}
            </section>
          ) : notice ? (
            <article className="detail">
              <span className="eyebrow">课程通知 · 合成数据</span>
              <h1>{notice.title}</h1>
              <p className="meta">
                {course(notice.courseId).name} · {notice.date}
              </p>
              <p className="body-text">{notice.body}</p>
            </article>
          ) : (
            <p role="alert">未找到该演示通知。</p>
          ))}
        {page === "materials" && (
          <>
            <aside className="demo-note">
              资料导入、下载与阅读尚未实现。以下仅展示合成资料元数据。
            </aside>
            <section className="panel">
              {courses.map((c) => (
                <div className="list-row" key={c.id}>
                  <span className="file-mark" aria-hidden="true">
                    PDF
                  </span>
                  <span className="row-copy">
                    <span className="row-title">{c.name} · 演示讲义</span>
                    <span className="meta">合成资料 · 无实际文件</span>
                  </span>
                  <span className="tag unknown">未实现阅读</span>
                </div>
              ))}
            </section>
          </>
        )}
        {page === "settings" && (
          <>
            <section className="panel settings">
              <dl>
                <dt>应用版本</dt>
                <dd>{VERSION} · Debug</dd>
                <dt>运行模式</dt>
                <dd>离线演示模式</dd>
                <dt>数据来源</dt>
                <dd>应用内置合成数据</dd>
                <dt>后端连接</dt>
                <dd>未连接 · 此版本未实现远程连接</dd>
                <dt>同步状态</dt>
                <dd>未同步，不含真实课程</dd>
                <dt>数据持久化</dt>
                <dd>仅内存展示，重新启动恢复演示状态</dd>
              </dl>
              <label htmlFor="theme">界面外观</label>
              <select
                id="theme"
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
              >
                <option value="system">跟随系统</option>
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            </section>
            <section className="panel limitations">
              <h2>当前未支持</h2>
              <p>
                校园登录、真实同步、连接服务、作业提交、文件导入与阅读、AI
                问答及消息推送。
              </p>
              <p>
                此 APK 不运行 Python 后端。手机的 localhost
                是手机本身，不代表电脑或云服务。
              </p>
              <p>
                Debug
                签名仅供测试；不同构建之间可能无法覆盖升级。离线演示不需要服务器或账号。
              </p>
            </section>
          </>
        )}
        <footer>ScholarOS · 合成数据，安心探索</footer>
      </main>
      <nav className="bottom-nav" aria-label="主导航">
        {navigation.map(([key, label], i) => (
          <button
            key={key}
            aria-current={page === key ? "page" : undefined}
            onClick={() => navigate(key)}
          >
            <Icon index={i} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <OfflineApp />
  </React.StrictMode>,
);
