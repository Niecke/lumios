import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const template = readFileSync(new URL("../nginx.conf.template", import.meta.url), "utf8");

interface Block {
  header: string;
  // Directives directly in this block (not in nested blocks), whitespace-normalised.
  directives: string[];
  children: Block[];
}

// Small nginx config parser: enough for the template. Braces inside quoted
// strings, comments and `${VAR}` placeholders do not open or close blocks.
function parse(src: string): Block {
  const root: Block = { header: "", directives: [], children: [] };
  const stack: Block[] = [root];
  let current = "";
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === "#") {
      while (i < src.length && src[i] !== "\n") i++;
      continue;
    }
    if (c === '"' || c === "'") {
      const end = src.indexOf(c, i + 1);
      assert.ok(end > i, "unterminated string in nginx template");
      current += src.slice(i, end + 1);
      i = end + 1;
      continue;
    }
    if (c === "$" && src[i + 1] === "{") {
      const end = src.indexOf("}", i);
      assert.ok(end > i, "unterminated ${ in nginx template");
      current += src.slice(i, end + 1);
      i = end + 1;
      continue;
    }
    if (c === "{") {
      const block: Block = { header: norm(current), directives: [], children: [] };
      stack[stack.length - 1].children.push(block);
      stack.push(block);
      current = "";
    } else if (c === "}") {
      assert.equal(norm(current), "", "directive without ';' before '}'");
      stack.pop();
      assert.ok(stack.length > 0, "unbalanced '}' in nginx template");
      current = "";
    } else if (c === ";") {
      stack[stack.length - 1].directives.push(norm(current));
      current = "";
    } else {
      current += c;
    }
    i++;
  }
  assert.equal(stack.length, 1, "unbalanced '{' in nginx template");
  return root;
}

function norm(s: string): string {
  return s.trim().replace(/\s+/g, " ");
}

const root = parse(template);
const server = root.children.find((b) => b.header === "server");
assert.ok(server, "server block not found");

function location(header: string): Block {
  const block = server!.children.find((b) => b.header === `location ${header}`);
  assert.ok(block, `location ${header} not found`);
  return block;
}

const serverHeaders = server.directives.filter((d) => d.startsWith("add_header "));

function csp(block: Block): string | undefined {
  return block.directives.find((d) => d.startsWith("add_header Content-Security-Policy "));
}

test("server level sends the four security headers", () => {
  for (const name of [
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
  ]) {
    assert.ok(
      serverHeaders.some((d) => d.startsWith(`add_header ${name} `)),
      `server-level ${name} missing`,
    );
  }
});

test("/assets/ is cached immutably for a year and has no SPA fallback", () => {
  const assets = location("/assets/");
  assert.deepEqual(
    assets.directives.filter((d) => d.startsWith("add_header Cache-Control ")),
    ["add_header Cache-Control $assets_cache_control always"],
  );
  assert.ok(assets.directives.includes("try_files $uri =404"));
});

test("/assets/ caches only hits; a 404 is no-store", () => {
  const map = root.children.find((b) => b.header === "map $status $assets_cache_control");
  assert.ok(map, "map $status $assets_cache_control not found");
  assert.deepEqual(map.directives, [
    '200 "public, max-age=31536000, immutable"',
    '304 "public, max-age=31536000, immutable"',
    'default "no-store"',
  ]);
});

test("index.html is always revalidated", () => {
  const index = location("= /index.html");
  assert.ok(index.directives.includes('add_header Cache-Control "no-cache" always'));
});

test("SPA fallback still redirects to /index.html", () => {
  assert.ok(location("/").directives.includes("try_files $uri $uri/ /index.html"));
});

for (const header of ["/assets/", "= /index.html"]) {
  test(`location ${header} repeats every server-level security header`, () => {
    const block = location(header);
    for (const directive of serverHeaders) {
      assert.ok(block.directives.includes(directive), `missing: ${directive}`);
    }
    assert.equal(csp(block), csp(server));
  });
}
