// Entirely synthetic fixtures. This module never imports the Web API client.
export type Course = { id: string; name: string; code: string; teacher: string; color: string; description: string };
export type Assignment = { id: string; courseId: string; title: string; deadline: string | null; submitted: boolean; body: string };
export type Notice = { id: string; courseId: string; title: string; date: string; body: string };
export const VERSION = "0.1.0-dev";
export const courses: Course[] = [
  { id: "power", name: "电力系统分析", code: "EE 301", teacher: "演示教师 A", color: "mint", description: "从电网结构到潮流计算，建立电力系统稳态分析的基本方法。此课程及全部资料均为合成演示内容。" },
  { id: "electronics", name: "电力电子技术基础", code: "EE 204", teacher: "演示教师 B", color: "peach", description: "认识功率半导体器件、整流电路与变换技术。课程安排仅用于展示界面，不代表真实教学计划。" },
  { id: "control", name: "自动控制原理", code: "EE 302", teacher: "演示教师 C", color: "lavender", description: "用数学模型理解反馈、稳定性与系统响应，探索控制系统的设计方法。" },
];
export function deadlineState(value: string | null, now = new Date()): { label: string; kind: string } {
  if (!value) return { label: "截止时间待定", kind: "unknown" };
  // Only accept full ISO timestamps with an explicit timezone, never ambiguous locale input.
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) return { label: "截止时间格式异常", kind: "unknown" };
  const date = new Date(value);
  if (date < now) return { label: "已逾期（演示）", kind: "overdue" };
  if (date.toDateString() === now.toDateString()) return { label: "今天截止", kind: "today" };
  return { label: "即将截止", kind: "upcoming" };
}
export function formatDeadline(value: string | null) {
  if (deadlineState(value).kind === "unknown") return deadlineState(value).label;
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value!));
}
export function makeDemo(now = new Date()) {
  const at = (offset: number) => { const d = new Date(now); d.setDate(d.getDate() + offset); d.setHours(23, 59, 59, 0); return d.toISOString().replace(/\.\d{3}Z$/, "Z"); };
  const assignments: Assignment[] = [
    { id: "flow", courseId: "power", title: "第 3 章 · 潮流计算练习", deadline: at(0), submitted: false, body: "绘制一个三节点系统的等值电路，并写出节点功率方程。请整理计算思路，比较不同初值对迭代的影响。\n\n这是一道合成演示作业。此版本不支持上传、提交或批改。" },
    { id: "rectifier", courseId: "electronics", title: "整流电路波形分析", deadline: at(2), submitted: false, body: "分析单相桥式整流电路的输出波形，说明负载变化的影响。示例仅用于演示作业详情。" },
    { id: "feedback", courseId: "control", title: "闭环系统稳定性分析", deadline: at(-2), submitted: false, body: "根据合成传递函数讨论闭环稳定性。本条展示过期作业的提示，不是真实待交记录。" },
    { id: "submitted", courseId: "power", title: "电力网络基础回顾", deadline: at(-4), submitted: true, body: "这条合成记录展示“已提交”状态。应用没有向任何学校系统提交内容。" },
    { id: "undated", courseId: "control", title: "反馈系统阅读笔记", deadline: null, submitted: false, body: "此演示记录没有截止日期，界面会如实显示待定。" },
    { id: "invalid", courseId: "electronics", title: "日期异常示例", deadline: "2026-invalid-date", submitted: false, body: "此条故意使用异常日期，验证应用不会崩溃或显示虚构的截止时间。" },
    ...Array.from({ length: 18 }, (_, i) => ({ id: `practice-${i}`, courseId: courses[i % courses.length].id, title: `拓展练习 ${i + 1}（合成）`, deadline: at(i + 3), submitted: false, body: "长列表交互演示，无需网络。此记录不是学校发布的作业。" })),
  ];
  const notices: Notice[] = [
    { id: "lab", courseId: "electronics", title: "实验准备事项", date: "演示公告 · 01", body: "请先阅读整流电路实验的基础概念。这里展示合成教师公告的完整内容；实验时间和地点尚未接入真实数据。" },
    { id: "chapter", courseId: "power", title: "本周学习重点：潮流计算", date: "演示公告 · 02", body: "本周演示课程围绕节点方程、导纳矩阵与迭代求解展开。所有课程与通知均为虚构数据。" },
    { id: "review", courseId: "control", title: "学习讨论与复习建议", date: "演示公告 · 03", body: "从典型阶跃响应出发，比较开环与闭环系统。此应用尚未接入课堂讨论或消息推送。" },
  ];
  return { assignments, notices };
}
export const navigation = [
  ["home", "首页"], ["courses", "课程"], ["assignments", "作业"], ["notices", "通知"], ["materials", "资料"], ["settings", "设置"],
] as const;
export function safeRoute(hash: string) {
  const value = hash.replace(/^#\/?/, "");
  return /^(home|courses|assignments|notices|materials|settings)(\/[a-z0-9-]+)?$/.test(value) ? value : "home";
}
