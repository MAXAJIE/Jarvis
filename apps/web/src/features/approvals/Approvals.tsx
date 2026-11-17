import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useApprovals } from "../../lib/approvals";

export default function Approvals({
  onDecided,
  query,
}: {
  onDecided: () => void;
  query: string;
}) {
  const queryClient = useQueryClient();
  const pending = useApprovals();

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approved" | "rejected" }) =>
      api(`/api/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      onDecided();
    },
  });

  const needle = query.trim().toLowerCase();
  const rows = (pending.data?.approvals ?? []).filter(
    (row) =>
      !needle ||
      row.tool_name.toLowerCase().includes(needle) ||
      row.summary.toLowerCase().includes(needle),
  );

  return (
    <div className="panel flex min-h-0 flex-1 flex-col">
      <div className="panel-head">
        <span className="flex-1">Approval Gate</span>
        <span>{rows.length} waiting</span>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {rows.length === 0 ? (
          <p className="text-[0.72rem] leading-relaxed text-[var(--color-mute)]">
            Nothing pending. External and destructive calls stop here and wait for you; the agent
            cannot approve itself.
          </p>
        ) : null}
        {rows.map((row) => (
          <div
            key={row.id}
            className="rounded border border-amber-700/50 bg-amber-500/5 p-2.5"
          >
            <div className="flex flex-wrap items-center gap-2 text-[0.62rem] text-amber-200">
              <span className="font-semibold tracking-[0.08em]">{row.tool_name}</span>
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 tracking-[0.1em]">
                {row.risk}
              </span>
              <span className="ml-auto text-amber-300/70">
                expires {row.expires_at.slice(0, 19).replace("T", " ")}
              </span>
            </div>
            <p className="mt-1.5 whitespace-pre-wrap text-[0.76rem] text-amber-50">{row.summary}</p>
            <div className="mt-2 flex gap-2">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => decide.mutate({ id: row.id, decision: "approved" })}
                disabled={decide.isPending}
              >
                Approve
              </button>
              <button
                className="btn btn-danger"
                type="button"
                onClick={() => decide.mutate({ id: row.id, decision: "rejected" })}
                disabled={decide.isPending}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
