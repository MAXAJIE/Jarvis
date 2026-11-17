import { useState } from "react";

import { ApiError, api, type Identity } from "../../lib/api";

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
      <form onSubmit={submit} className="card w-full max-w-sm space-y-3 p-6">
        <h1 className="text-lg font-semibold">Jarvis</h1>
        <p className="text-sm text-slate-400">One operator. Password plus a TOTP code.</p>
        <input
          className="field"
          placeholder="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <input
          className="field"
          placeholder="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <input
          className="field"
          placeholder="6-digit code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={totp}
          onChange={(event) => setTotp(event.target.value)}
        />
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <button className="btn btn-primary w-full" type="submit" disabled={busy}>
          {busy ? "checking…" : "Sign in"}
        </button>
        <p className="text-xs text-slate-500">
          First run: <code>python scripts/setup_operator.py</code> writes the hash and TOTP secret to
          .env.
        </p>
      </form>
    </div>
  );
}
