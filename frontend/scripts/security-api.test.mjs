import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import test from "node:test";
import ts from "typescript";

// Compile the real helper with Vite's development env substituted; no server,
// browser credentials, storage or network is involved.
const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText.replaceAll("import.meta.env", "({ DEV: true })");
const api = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  return { ok: true, json: async () => ({ status: "ready" }) };
};

test("owner GET, POST and multipart carry the token only in the header", async () => {
  const synthetic = "synthetic-".repeat(5);
  api.setAccessToken(synthetic);
  await api.apiGet("/api/settings/status");
  await api.apiPost("/api/settings/local", { learn_username: "synthetic" });
  const form = new FormData();
  form.append("file", new Blob(["synthetic"]), "sample.md");
  await api.apiFetch("/api/upload", { method: "POST", body: form });
  for (const { url, init } of calls) {
    assert.equal(init.headers.get("Authorization"), `Bearer ${synthetic}`);
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.ok(!url.includes(synthetic));
  }
  assert.equal(calls[1].init.headers.get("Content-Type"), "application/json");
  assert.equal(calls[2].init.headers.get("Content-Type"), null);
  assert.equal(calls[2].init.body, form);
});

test("locking clears the in-memory token", async () => {
  api.setAccessToken("");
  await api.apiGet("/api/settings/status");
  assert.equal(calls.at(-1).init.headers.get("Authorization"), null);
});
