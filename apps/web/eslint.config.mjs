/* P1 code-review 2026-11-18: ESLint akhirnya dipasang. Sebelumnya
   20+ `eslint-disable-next-line` di kode tidak pernah divalidasi tooling
   apa pun karena ESLint tidak terpasang. Konfigurasi minimal: aturan
   core-web-vitals + TypeScript bawaan Next. Jalankan `npm run lint`
   setelah `npm ci`; perbaiki pelanggaran baru sebelum merge, jangan
   menambah disable tanpa komentar alasan.
   eslint-config-next 15.5 hanya menyediakan konfigurasi legacy
   (eslintrc), bukan flat config, jadi dipakai lewat FlatCompat.
   Impor langsung "eslint-config-next/core-web-vitals" gagal dua kali:
   tanpa field "exports" di paket itu ESM menuntut ekstensi .js, dan
   isinya objek legacy { extends: [...] } yang tidak bisa di-spread
   sebagai array flat config. */
import { defineConfig, globalIgnores } from "eslint/config";
import { FlatCompat } from "@eslint/eslintrc";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const compat = new FlatCompat({ baseDirectory: __dirname });

export default defineConfig([
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  globalIgnores([
    ".next/**",
    "out/**",
    "node_modules/**",
    "next-env.d.ts",
  ]),
]);
