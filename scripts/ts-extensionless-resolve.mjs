// Node's built-in TypeScript type-stripping (used by `node --test` to run scripts/*.test.mjs
// against lib/*.ts directly, with no build step) resolves relative specifiers with plain ESM
// rules: an extensionless import like "./sse" is never resolved against a co-located "sse.ts" the
// way TypeScript's own "bundler" moduleResolution (tsconfig.json) resolves it. That extensionless
// style is this codebase's convention throughout lib/ (e.g. lib/api.ts importing "./sse", "./types"),
// so lib/api.ts is written the same way as everything else, not adjusted for this test's sake.
//
// This loader hook is the fix on the *test* side instead: it only ever intervenes when Node's own
// resolution already failed and the specifier is relative, trying ".ts" (and ".tsx", for
// completeness) before giving up. Anything Node resolves natively -- bare package specifiers,
// already-extensioned files, non-existent modules -- passes straight through untouched.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const CANDIDATE_EXTENSIONS = [".ts", ".tsx"];

export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    const isBareRelative = (specifier.startsWith("./") || specifier.startsWith("../")) && !/\.[a-zA-Z0-9]+$/.test(specifier);
    if (error?.code !== "ERR_MODULE_NOT_FOUND" || !isBareRelative || !context.parentURL) throw error;
    for (const extension of CANDIDATE_EXTENSIONS) {
      const candidateSpecifier = `${specifier}${extension}`;
      const candidateUrl = new URL(candidateSpecifier, context.parentURL);
      if (existsSync(fileURLToPath(candidateUrl))) return nextResolve(candidateSpecifier, context);
    }
    throw error;
  }
}
