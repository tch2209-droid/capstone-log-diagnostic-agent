import { AppHeader } from "../app-header";
import { getChatGPTUser } from "../chatgpt-auth";
import { OrchestrationDemo } from "./orchestration-demo";

export const dynamic = "force-dynamic";

export default async function OrchestrationPage() {
  const user = await getChatGPTUser();
  const reviewerName = user?.displayName ?? "Local reviewer";

  return (
    <main className="console-shell orchestration-shell">
      <AppHeader
        active="orchestration"
        reviewerName={reviewerName}
        isAuthenticated={Boolean(user)}
        statusLabel="Live orchestration · Guided replay"
        statusTone="demo"
      />
      <OrchestrationDemo />
    </main>
  );
}
