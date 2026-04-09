import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { TopNav } from "@/components/layout/top-nav";
import { BottomTabs } from "@/components/layout/bottom-tabs";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "Open Brain",
  description: "Personal memory & knowledge dashboard",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-visual",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full bg-background text-on-surface font-body antialiased">
        <AuthProvider>
          <TopNav />
          <Sidebar />
          <main className="ml-0 md:ml-64 pt-16 pb-[calc(5rem+env(safe-area-inset-bottom,0px))] md:pb-8 px-6 md:px-10 max-w-[1400px] mx-auto">
            {children}
          </main>
          <BottomTabs />
          <Toaster />
        </AuthProvider>
      </body>
    </html>
  );
}
