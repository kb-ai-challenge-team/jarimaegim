// Bootstrap for --import: registers ts-extensionless-resolve.mjs as a module customization hook
// (the non-deprecated replacement for --experimental-loader) before scripts/*.test.mjs runs.
import { register } from "node:module";

register("./ts-extensionless-resolve.mjs", import.meta.url);
