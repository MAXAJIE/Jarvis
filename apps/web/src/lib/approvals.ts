import { useQuery } from "@tanstack/react-query";

import { api, type ApprovalRequest } from "./api";

export interface PendingApprovals {
  approvals: ApprovalRequest[];
  count: number;
}

/**
 * One query key, one shape.
 *
 * The nav badge and the Approvals page used to declare separate queryFns under
 * the same key, so React Query shared a single cache slot between them: the page
 * wrote the whole payload, the badge expected a number, and the badge rendered
 * "Approvals ([object Object])". Both now read this hook.
 */
export function useApprovals(enabled = true) {
  return useQuery<PendingApprovals>({
    queryKey: ["approvals"],
    queryFn: () => api<PendingApprovals>("/api/approvals"),
    enabled,
    refetchInterval: enabled ? 15_000 : false,
  });
}
