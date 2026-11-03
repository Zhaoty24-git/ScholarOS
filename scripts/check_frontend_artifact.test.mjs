import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm, symlink } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { verifyArtifact, publishArtifact } from "./check_frontend_artifact.mjs";

async function fixture(fn) {
  const root = await mkdtemp(join(tmpdir(), "scholaros-artifact-test-"));
  try {
    await mkdir(join(root, "assets"));
    await writeFile(join(root, "index.html"), '<script src="/app/assets/app.js"></script><link href="/app/assets/app.css">');
    await writeFile(join(root, "assets/app.js"), "synthetic");
    await writeFile(join(root, "assets/app.css"), "body{}");
    await fn(root);
  } finally { await rm(root, { recursive: true, force: true }); }
}
test("compiled assets and hashes verified", () => fixture(async (root) => assert.equal((await verifyArtifact(root)).length, 3)));
test("private files fail the build", () => fixture(async (root) => { await writeFile(join(root, ".env"), "synthetic"); await assert.rejects(verifyArtifact(root)); }));
test("environment canary leakage fails", () => fixture(async (root) => { await writeFile(join(root, "assets/app.js"), "synthetic-canary"); await assert.rejects(verifyArtifact(root, "synthetic-canary")); }));
test("missing assets fail", () => fixture(async (root) => { await rm(join(root, "assets/app.css")); await assert.rejects(verifyArtifact(root)); }));
test("symlinks cannot smuggle other files", () => fixture(async (root) => { await symlink(join(root, "index.html"), join(root, "assets/link.js")); await assert.rejects(verifyArtifact(root)); }));
test("published artifacts exist and existing output is never overwritten", () => fixture(async (root) => {
  const parent = await mkdtemp(join(tmpdir(), "scholaros-publish-"));
  try {
    const output = join(parent, "dist");
    await publishArtifact(root, output, root);
    assert.equal((await verifyArtifact(output)).length, 3);
    await assert.rejects(publishArtifact(root, output, root));
    assert.equal((await verifyArtifact(output)).length, 3);
  } finally { await rm(parent, { recursive: true, force: true }); }
}));
test("output cannot enter the checkout via a symlink", () => fixture(async (root) => {
  const parent = await mkdtemp(join(tmpdir(), "scholaros-link-"));
  try {
    await symlink(root, join(parent, "checkout"));
    await assert.rejects(publishArtifact(root, join(parent, "checkout", "new-dir"), root));
  } finally { await rm(parent, { recursive: true, force: true }); }
}));
