import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useApprovals } from "../../lib/approvals";

export default function Approvals({ onDecided }: { onDecided: () => void }) {
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
      onDecided();
    },
  });

  const rows = pending.data?.approvals ?? [];

  return (
    <div className="card space-y-3 p-4">
      <h2 className="text-sm font-semibold">Waiting for you</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing pending. External and destructive calls stop here.</p>
      ) : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.id} className="rounded-lg border border-amber-800 bg-amber-950/30 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-amber-200">
              <span className="font-semibold">{row.tool_name}</span>
              <span>{row.risk}</span>
              <span className="text-amber-400/70">expires {row.expires_at.slice(0, 19)}</span>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-amber-50">{row.summary}</p>
            <div className="mt-2 flex gap-2">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => decide.mutate({ id: row.id, decision: "approved" })}
              >
                Approve
              </button>
              <button
                className="btn btn-danger"
                type="button"
                onClick={() => decide.mutate({ id: row.id, decision: "rejected" })}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
