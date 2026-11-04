// Build only Git-tracked frontend inputs, never local .env or node_modules.
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, writeFile, mkdir, cp, lstat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { verifyArtifact, publishArtifact } from "./check_frontend_artifact.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stage = await mkdtemp(resolve(tmpdir(), "scholaros-frontend-"));
try {
  const paths = execFileSync("git", ["ls-files", "-z", "--", "frontend"], { cwd: root, encoding: "utf8" }).split("\0").filter(Boolean);
  if (!paths.includes("frontend/package-lock.json")) throw new Error("Frontend lock missing");
  for (const path of paths) {
    const name = relative("frontend", path);
    if (name.startsWith("..") || /(?:^|\/)(?:\.env(?:\..*)?|node_modules|dist)(?:\/|$)/.test(name)) throw new Error("Unsafe tracked frontend input");
    const source = resolve(root, path);
    if ((await lstat(source)).isSymbolicLink()) throw new Error("Frontend source symlink");
    await mkdir(dirname(resolve(stage, name)), { recursive: true });
    await cp(source, resolve(stage, name));
  }
  const emptyConfig = resolve(stage, "empty.npmrc");
  await writeFile(emptyConfig, "");
  const environment = {};
  for (const key of ["PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE"]) {
    if (process.env[key]) environment[key] = process.env[key];
  }
  const canary = "synthetic-build-canary-" + randomUUID();
  Object.assign(environment, { NPM_CONFIG_USERCONFIG: emptyConfig, NPM_CONFIG_GLOBALCONFIG: resolve(stage, "global.npmrc"), NPM_CONFIG_CACHE: resolve(stage, "npm-cache"), NPM_CONFIG_REGISTRY: "https://registry.npmjs.org/", VITE_CI_CANARY: canary, LEARN_PASSWORD: canary });
  await writeFile(environment.NPM_CONFIG_GLOBALCONFIG, "");
  function run(command, args) {
    const result = spawnSync(command, args, { cwd: stage, env: environment, stdio: "inherit", timeout: 180_000 });
    if (result.error || result.status !== 0) throw new Error("Frontend command failed: " + command);
  }
  run("node", ["--version"]);
  run("npm", ["--version"]);
  run("npm", ["ci", "--ignore-scripts", "--no-audit", "--no-fund"]);
  run("npm", ["run", "test:security"]);
  run("node", ["node_modules/typescript/bin/tsc", "--noEmit"]);
  run("npm", ["run", "build"]);
  const manifest = await verifyArtifact(resolve(stage, "dist"), canary);
  const outputFlag = process.argv.indexOf("--output");
  if (outputFlag !== -1) {
    if (!process.argv[outputFlag + 1]) throw new Error("Output path required");
    await publishArtifact(resolve(stage, "dist"), process.argv[outputFlag + 1], root);
  }
  console.log(JSON.stringify({ artifact_verified: true, files: manifest }));
} finally {
  await rm(stage, { recursive: true, force: true });
}
