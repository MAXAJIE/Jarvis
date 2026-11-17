import { useQuery } from "@tanstack/react-query";

import { api, type Dashboard as DashboardData } from "../../lib/api";

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

export default function Dashboard() {
  const data = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<DashboardData>("/api/metrics/dashboard"),
    refetchInterval: 20_000,
  });

  if (data.isLoading) return <div className="card p-4 text-sm text-slate-400">loading…</div>;
  if (data.error || !data.data) {
    return <div className="card p-4 text-sm text-red-400">dashboard unavailable</div>;
  }

  const metrics: { label: string; value: string; hint?: string }[] = [
    { label: "Tasks completed", value: String(data.data.tasks_completed), hint: "this month" },
    { label: "Failures", value: String(data.data.failures), hint: "tool runs that raised" },
    {
      label: "API usage",
      value: `${data.data.api_calls} calls`,
      hint: `${data.data.tokens_used.toLocaleString()} tokens`,
    },
    { label: "Voice minutes", value: data.data.voice_minutes.toFixed(2) },
    {
      label: "Spend this month",
      value: money(data.data.spend_usd),
      hint: `ceiling ${money(data.data.ceiling_usd)}`,
    },
    {
      label: "Left for usage",
      value: money(data.data.remaining_usd),
      hint: `fixed ${money(data.data.fixed_usd)} already counted`,
    },
  ];

  return (
    <div className="space-y-4">
      {data.data.alarm ? (
        <div className="rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-200">
          Spend alarm: {money(data.data.spend_usd)} of {money(data.data.ceiling_usd)} committed.
          External tools stop at the ceiling.
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {metrics.map((metric) => (
          <div key={metric.label} className="card p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">{metric.label}</div>
            <div className="mt-1 text-2xl font-semibold">{metric.value}</div>
            {metric.hint ? <div className="text-xs text-slate-500">{metric.hint}</div> : null}
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        Every number is a SQL aggregate over cost_ledger, tool_runs and tasks for {data.data.period_start}.
        Fixed costs are a floor, so a partial ledger cannot under-report spend.
      </p>
    </div>
  );
}
