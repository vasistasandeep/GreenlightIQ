/**
 * Deep-Dive Title Evaluation route (`/titles/[id]`, R15, R30.4).
 *
 * Thin server-component shell that forwards the dynamic title id to the
 * {@link TitleEvaluationView} client component, which fetches the scorecard via
 * the typed API client (carrying the ambient session credential) and renders the
 * metadata radar, financial accordion, negotiation leverage, and explanation
 * panels — with a pending state when no completed valuation exists (R15.4).
 */

import { TitleEvaluationView } from "./_components/title-evaluation-view";

export default function TitleEvaluationPage({
  params,
}: {
  params: { id: string };
}) {
  return <TitleEvaluationView titleId={params.id} />;
}
