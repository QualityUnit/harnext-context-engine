import { NavBar } from "@/components/NavBar";

export default function ProjectsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <NavBar />
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </>
  );
}
