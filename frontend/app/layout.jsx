import "./globals.css";
import TopBar from "../components/TopBar";

export const metadata = {
  title: "BudgetBench — Executive Dashboard",
  description: "Compare IBM BOB, Claude, and Copilot on cost, speed, and quality against your Planning Analytics budget.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <TopBar />
        <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
