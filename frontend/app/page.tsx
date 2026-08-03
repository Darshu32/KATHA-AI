import type { Metadata } from "next";

import Landing from "@/components/landing/landing";

/* Root → the landing page. (Was a redirect to /chat while the landing was
 * deferred.) /chat and /design remain the app surfaces, linked from here. */
export const metadata: Metadata = {
  title: "KATHA — The universal OS for architects",
  description:
    "Brief a project in plain language and KATHA returns a costed, code-checked design — working drawings, analysis diagrams, and BIM-ready exports to Revit, AutoCAD and ArchiCAD.",
};

export default function HomePage() {
  return <Landing />;
}
