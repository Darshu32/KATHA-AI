import { redirect } from "next/navigation";

/* Root → chat. Landing page deferred — user opens the app and lands
 * directly in the conversation surface, the way every modern AI app
 * (Claude, ChatGPT, Perplexity) does it. */
export default function HomePage() {
  redirect("/chat");
}
