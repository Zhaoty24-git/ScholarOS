import { lstat, readFile, readdir, realpath, mkdir, cp } from "node:fs/promises";
import { resolve, relative, extname, dirname, basename, sep } from "node:path";
import { createHash } from "node:crypto";

export async function publishArtifact(source, output, checkout) {
  const destination = resolve(await realpath(dirname(resolve(output))), basename(output));
  const root = await realpath(checkout);
  if (destination === root || destination.startsWith(root + sep)) throw new Error("CI artifact must be outside checkout");
  const original = await realpath(source);
  if (destination === original || destination.startsWith(original + sep)) throw new Error("Artifact cannot contain itself");
  await mkdir(destination); // exclusive: never overwrite/delete existing output
  for (const name of await readdir(original)) {
    await cp(resolve(original, name), resolve(destination, name), { recursive: true, force: false, errorOnExist: true });
  }
}

export async function verifyArtifact(directory, canary = "") {
  const root = resolve(directory);
  const files = [];
  async function visit(dir) {
    for (const name of await readdir(dir)) {
      const path = resolve(dir, name);
      const stat = await lstat(path);
      if (stat.isSymbolicLink()) throw new Error("Artifact contains a symlink");
      if (stat.isDirectory()) { await visit(path); continue; }
      const local = relative(root, path).replaceAll("\\", "/");
      if (local !== "index.html" && (!local.startsWith("assets/") || ![".js", ".css", ".woff", ".woff2", ".png", ".svg", ".jpg", ".webp"].includes(extname(local)))) {
        throw new Error("Unexpected artifact file");
      }
      if (/(?:^|[./_-])(?:cookies?|sessions?|credentials|token|env|db)(?:[./_-]|$)/i.test(local)) throw new Error("Private artifact name");
      if (stat.size > 5 * 1024 * 1024) throw new Error("Artifact file unexpectedly large");
      const data = await readFile(path);
      if (canary && data.includes(Buffer.from(canary))) throw new Error("Build environment canary leaked");
      files.push({ path: local, bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") });
    }
  }
  await visit(root);
  const html = await readFile(resolve(root, "index.html"), "utf8");
  const references = [...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)].map((m) => m[1]).filter((v) => !v.startsWith("data:"));
  if (!references.some((v) => v.endsWith(".js")) || !references.some((v) => v.endsWith(".css"))) throw new Error("Missing compiled scripts/styles");
  for (const value of references) {
    if (!value.startsWith("/app/assets/") || value.includes("..") || !files.some((f) => "/app/" + f.path === value)) throw new Error("Missing or external asset reference");
  }
  if (files.reduce((sum, f) => sum + f.bytes, 0) > 20 * 1024 * 1024) throw new Error("Artifact unexpectedly large");
  return files.sort((a, b) => a.path.localeCompare(b.path));
}
