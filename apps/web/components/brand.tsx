export function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <span className={`brand ${inverse ? "brandInverse" : ""}`}>
      <span className="brandMark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="brandWord">autonomerce</span>
    </span>
  );
}
