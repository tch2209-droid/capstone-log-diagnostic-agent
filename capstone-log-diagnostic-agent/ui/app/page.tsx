import { getChatGPTUser } from "./chatgpt-auth";
import { ReviewConsole } from "./review-console";
import { seedReviews } from "../db/seed";

export const dynamic = "force-dynamic";

export default async function Home() {
  const user = await getChatGPTUser();
  const initialReviews = seedReviews.map((review) => ({
    ...review,
    latestDecision: null,
    diagnosisDecisions: [],
    jiraTickets: [],
  }));

  return (
    <ReviewConsole
      initialReviews={initialReviews}
      reviewerName={user?.displayName ?? "Local reviewer"}
      isAuthenticated={Boolean(user)}
    />
  );
}
