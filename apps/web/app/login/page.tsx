"use client";

import { useState } from "react";

// Placeholder Fase 0 — BUKAN desain final. Desain final (vibekoding) di Fase 2.
export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setNote("Backend API belum tersedia — login aktif mulai Fase 1.");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-neutral-200 bg-white p-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <h1 className="text-xl font-semibold tracking-tight">NetraVision</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Sistem pemantauan CCTV — masuk untuk melanjutkan
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label
              htmlFor="username"
              className="mb-1 block text-sm font-medium"
            >
              Nama pengguna
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-neutral-500 dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="mb-1 block text-sm font-medium"
            >
              Kata sandi
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-neutral-500 dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
          <button
            type="submit"
            className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-white"
          >
            Masuk
          </button>
          {note && (
            <p className="text-sm text-amber-600 dark:text-amber-400">{note}</p>
          )}
        </form>
      </div>
    </main>
  );
}
