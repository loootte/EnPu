import { RecognizePage } from "./pages/RecognizePage";

/**
 * EnPu desktop root.
 * #4 shell → #5 import / preview / results UI.
 */
function App() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-slate-100">
      <RecognizePage />
    </div>
  );
}

export default App;
