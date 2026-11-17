import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import Approvals from "./features/approvals/Approvals";
import Login from "./features/auth/Login";
import Chat from "./features/chat/Chat";
import Dashboard from "./features/dashboard/Dashboard";
import Tasks from "./features/tasks/Tasks";
import { ApiError, api, type Identity } from "./lib/api";
import { useApprovals } from "./lib/approvals";

type Tab = "chat" | "tasks" | "approvals" | "dashboard";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "tasks", label: "Tasks" },
  { id: "approvals", label: "Approvals" },
  { id: "dashboard", label: "Dashboard" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const queryClient = useQueryClient();

  const me = useQuery<Identity | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Identity>("/api/auth/me");
      } catch (exc) {
        if (exc instanceof ApiError && exc.status === 401) return null;
        throw exc;
      }
    },
  });

  const pending = useApprovals(Boolean(me.data));

  if (me.isLoading) {
    return <div className="p-6 text-sm text-slate-400">loading…</div>;
  }
  if (!me.data) {
    return (
      <Login
        onDone={(identity) => {
          queryClient.setQueryData(["me"], identity);
        }}
      />
    );
  }

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    queryClient.setQueryData(["me"], null);
    queryClient.clear();
  }

  return (
    <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <span className="mr-2 font-semibold">Jarvis</span>
        {TABS.map((entry) => (
          <button
            key={entry.id}
            className={`btn ${tab === entry.id ? "btn-primary" : ""}`}
            onClick={() => setTab(entry.id)}
            type="button"
          >
            {entry.label}
            {entry.id === "approvals" && pending.data?.count ? ` (${pending.data.count})` : ""}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500">{me.data.email}</span>
        <button className="btn" onClick={logout} type="button">
          Sign out
        </button>
      </header>

      <main className="min-h-0 flex-1">
        {tab === "chat" ? <Chat onDecided={() => void queryClient.invalidateQueries()} /> : null}
        {tab === "tasks" ? <Tasks /> : null}
        {tab === "approvals" ? <Approvals onDecided={() => void queryClient.invalidateQueries()} /> : null}
        {tab === "dashboard" ? <Dashboard /> : null}
      </main>
    </div>
  );
}
