import Image from "next/image";

/**
 * The ShopperMind lockup. Both theme variants are rendered and CSS picks one, rather
 * than swapping the `src` from React state — the theme class is applied before first
 * paint by the inline script in the root layout, so a state-driven swap would flash the
 * wrong logo on every load.
 *
 * `mark` renders just the compass, for the collapsed sidebar where an 8.7:1 wordmark
 * would be a few pixels tall and unreadable.
 */
export function BrandLogo({
  height = 26,
  mark = false,
  priority = false,
}: {
  height?: number;
  mark?: boolean;
  priority?: boolean;
}) {
  const src = mark ? "shoppermind-mark" : "shoppermind";
  const w = mark ? 128 : 640;
  const h = mark ? 128 : 74;

  return (
    <span className="brand" style={{ height }} aria-label="ShopperMind" role="img">
      <Image
        src={`/${src}-light.png`}
        alt=""
        width={w}
        height={h}
        className="brand__img brand__img--light"
        style={{ height }}
        priority={priority}
        unoptimized
      />
      <Image
        src={`/${src}-dark.png`}
        alt=""
        width={w}
        height={h}
        className="brand__img brand__img--dark"
        style={{ height }}
        priority={priority}
        unoptimized
      />
    </span>
  );
}
