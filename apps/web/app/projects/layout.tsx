// Projects run inside the full-bleed dashboard shell (its own sidebar), so this
// layout is just a pass-through — no global NavBar.
export default function ProjectsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
