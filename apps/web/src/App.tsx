import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import Approvals from "./features/approvals/Approvals";
import Login from "./features/auth/Login";
import Chat from "./features/chat/Chat";
import { CommandCenter } from "./features/core/CommandCenter";
import { SystemView } from "./features/core/SystemView";
import { MemoryView } from "./features/memory/MemoryView";
import { BottomBar } from "./features/shell/BottomBar";
import { MobileNav, Sidebar, type Section } from "./features/shell/Sidebar";
import { TopBar } from "./features/shell/TopBar";
import Tasks from "./features/tasks/Tasks";
import { ToolsView } from "./features/tools/ToolsView";
import { ApiError, api, type Identity } from "./lib/api";
import { useApprovals } from "./lib/approvals";
import { useOverview } from "./lib/overview";

export default function App() {
  const [section, setSection] = useState<Section>("command");
  const [search, setSearch] = useState("");
  const [prompt, setPrompt] = useState<string | null>(null);
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

  const signedIn = Boolean(me.data);
  const overview = useOverview(signedIn);
  const approvals = useApprovals(signedIn);

  if (me.isLoading) {
    return (
      <div className="grid h-full place-items-center text-[0.8rem] text-[var(--color-mute)]">
        connecting to the core…
      </div>
    );
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

  const voiceReady = Boolean(overview.data?.voice.transport_ready);
  const voiceHint = overview.data
    ? !overview.data.voice.stt_ready || !overview.data.voice.tts_ready
      ? `Voice is offline: ${[
          !overview.data.voice.stt_ready ? "DEEPGRAM_API_KEY" : "",
          !overview.data.voice.tts_ready ? overview.data.voice.tts_key_env : "",
        ]
          .filter(Boolean)
          .join(" and ")} ${
          !overview.data.voice.stt_ready && !overview.data.voice.tts_ready ? "are" : "is"
        } empty. Typing works now.`
      : "Voice is available."
    : "Loading voice state…";

  /** The shell keeps one poll; panels read the same snapshot. */
  const refreshApprovals = () => {
    void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    void queryClient.invalidateQueries({ queryKey: ["overview"] });
  };

  function promptThenChat(text: string) {
    setPrompt(text);
    setSection("chat");
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar
        identity={me.data}
        overview={overview.data}
        query={search}
        onQuery={setSearch}
        onSignOut={() => void logout()}
      />

      <div className="flex min-h-0 flex-1">
        <Sidebar section={section} onSection={setSection} overview={overview.data} />

        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3">
          <MobileNav section={section} onSection={setSection} />
          {!overview.data ? (
            <div className="panel grid flex-1 place-items-center text-[0.78rem] text-[var(--color-mute)]">
              reading telemetry…
            </div>
          ) : (
            <>
              {section === "command" ? (
                <CommandCenter
                  overview={overview.data}
                  onPrompt={promptThenChat}
                  onSection={setSection}
                  onChanged={refreshApprovals}
                />
              ) : null}
              {section === "chat" ? (
                <Chat
                  onDecided={refreshApprovals}
                  voiceReady={voiceReady}
                  voiceHint={voiceHint}
                  prompt={prompt}
                  onPromptConsumed={() => setPrompt(null)}
                />
              ) : null}
              {section === "tasks" ? <Tasks query={search} /> : null}
              {section === "approvals" ? (
                <Approvals query={search} onDecided={refreshApprovals} />
              ) : null}
              {section === "core" ? <SystemView overview={overview.data} /> : null}
              {section === "tools" ? <ToolsView overview={overview.data} query={search} /> : null}
              {section === "memory" ? (
                <MemoryView overview={overview.data} onOpenChat={() => setSection("chat")} />
              ) : null}
            </>
          )}
        </main>
      </div>

      <BottomBar
        overview={overview.data}
        listening={false}
        onTalk={() => setSection("chat")}
        onType={() => setSection("chat")}
      />

      {approvals.data?.count ? (
        <div className="pointer-events-none fixed bottom-20 right-4 z-10">
          <button
            type="button"
            className="pointer-events-auto btn btn-primary"
            onClick={() => setSection("approvals")}
          >
            {approvals.data.count} awaiting approval
          </button>
        </div>
      ) : null}
    </div>
  );
}
