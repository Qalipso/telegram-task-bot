export default function Home() {
  return (
    <main style={{ maxWidth: 720, margin: "4rem auto", padding: "0 1.5rem" }}>
      <h1>AI Work Intelligence Platform</h1>
      <p style={{ color: "#555" }}>
        Stage 1 — Foundation. Services: <code>api</code>, <code>worker</code>,{" "}
        <code>postgres</code>, <code>redis</code>, <code>web</code>.
      </p>
      <p>
        Web health: <a href="/api/health">/api/health</a>
      </p>
    </main>
  );
}
