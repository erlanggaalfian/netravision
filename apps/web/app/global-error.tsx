"use client";

/* P0 code-review 2026-11-18: error boundary level root (global-error).
   Menangkap error di layout root sendiri — wajib me-render <html> dan
   <body> sendiri karena layout root ikut gagal saat error ini tampil. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="id">
      <body>
        <div
          style={{
            display: "flex",
            minHeight: "100dvh",
            alignItems: "center",
            justifyContent: "center",
            background: "#020617",
            padding: 20,
            fontFamily: "sans-serif",
          }}
        >
          <div style={{ textAlign: "center", maxWidth: 360 }}>
            <p
              style={{
                fontSize: 18,
                fontWeight: 700,
                color: "#fff",
                margin: "0 0 8px",
              }}
            >
              Terjadi kesalahan
            </p>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.6,
                color: "#94a3b8",
                margin: "0 0 24px",
              }}
            >
              NetraVision gagal dimuat. Coba muat ulang halaman.
            </p>
            <button
              type="button"
              onClick={() => reset()}
              style={{
                minHeight: 48,
                width: "100%",
                cursor: "pointer",
                border: "none",
                borderRadius: 12,
                background: "#0284c7",
                color: "#fff",
                fontSize: 16,
                fontWeight: 600,
              }}
            >
              Coba lagi
            </button>
            {error?.digest ? (
              <p style={{ fontSize: 12, color: "#475569", marginTop: 16 }}>
                Kode: {error.digest}
              </p>
            ) : null}
          </div>
        </div>
      </body>
    </html>
  );
}
