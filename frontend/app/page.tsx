import { AuthProvider } from "./AuthContext";
import ProjectWorkspace from "./ProjectWorkspace";

export default function Home() {
  return (
    <AuthProvider>
      <ProjectWorkspace />
    </AuthProvider>
  );
}
