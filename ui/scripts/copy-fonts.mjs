// Copies the bundled open-license fonts into public/fonts so the UI works offline.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "fonts");
mkdirSync(out, { recursive: true });

const files = [
  ["pretendard/dist/web/variable/woff2/PretendardVariable.woff2", "PretendardVariable.woff2"],
  ...[300, 400, 500, 600].map((w) => [
    `@fontsource/chakra-petch/files/chakra-petch-latin-${w}-normal.woff2`,
    `ChakraPetch-${w}.woff2`,
  ]),
];

for (const [src, dest] of files) {
  copyFileSync(join(root, "node_modules", src), join(out, dest));
}
console.log(`fonts: copied ${files.length} files to public/fonts`);
