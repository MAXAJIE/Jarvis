import { useState } from "react";

import { ApiError, api, type Identity } from "../../lib/api";
import { Waveform } from "../core/Orb";

/**
 * The door, in the same deck as the command center.
 *
 * It carried `card` from the old light layout; that class disappeared with the
 * redesign, which left the first screen an unstyled form. Anything the operator
 * sees before signing in has to look like the thing they signed up for.
 */
export default function Login({ onDone }: { onDone: (identity: Identity) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const identity = await api<Identity>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, totp }),
      });
      onDone(identity);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-4 flex flex-col items-center gap-2 text-center">
          <div className="grid h-14 w-14 place-items-center rounded-full border border-cyan-500/50 bg-cyan-500/10 text-cyan-300 shadow-[0_0_28px_rgba(34,211,238,0.35)]">
            <svg
              viewBox="0 0 24 24"
              className="h-7 w-7"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            >
              <circle cx="12" cy="12" r="7.5" />
              <ellipse cx="12" cy="12" rx="10" ry="4" />
              <circle cx="12" cy="12" r="2" />
            </svg>
          </div>
          <div className="text-base font-semibold tracking-[0.36em] text-cyan-100">JARVIS</div>
          <div className="text-[0.6rem] tracking-[0.26em] text-[var(--color-mute)]">
            COMMAND CENTER · RESTRICTED
          </div>
          <Waveform state="idle" bars={30} />
        </div>

        <form onSubmit={submit} className="panel space-y-3 p-5">
          <p className="text-[0.7rem] leading-relaxed text-[var(--color-mute)]">
            One operator. Password plus a TOTP code — no second account, no password reset by
            email.
          </p>

          <label className="block space-y-1">
            <span className="text-[0.6rem] tracking-[0.16em] text-[var(--color-mute)]">EMAIL</span>
            <input
              className="field"
              placeholder="operator@localhost"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[0.6rem] tracking-[0.16em] text-[var(--color-mute)]">
              PASSWORD
            </span>
            <input
              className="field"
              placeholder="••••••••••••"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[0.6rem] tracking-[0.16em] text-[var(--color-mute)]">
              6-DIGIT CODE
            </span>
            <input
              className="field kpi tracking-[0.4em]"
              placeholder="000000"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={totp}
              onChange={(event) => setTotp(event.target.value)}
            />
          </label>

          {error ? (
            <p className="rounded border border-rose-700/50 bg-rose-500/10 px-2 py-1.5 text-[0.7rem] text-rose-200">
              {error}
            </p>
          ) : null}

          <button className="btn btn-primary w-full" type="submit" disabled={busy}>
            {busy ? "checking…" : "Sign in"}
          </button>

          <p className="text-[0.62rem] leading-relaxed text-[var(--color-mute)]">
            First run: <code className="text-cyan-200">python scripts/setup_operator.py</code> writes
            the hash and TOTP secret to <code className="text-cyan-200">.env</code>.
          </p>
        </form>

        <p className="mt-3 text-center text-[0.6rem] text-[var(--color-mute)]">
          Loopback only · 127.0.0.1:8000 · single user
        </p>
      </div>
    </div>
  );
}
