import markWhite from "../images/logo-mark-white.png";
import horizontalColor from "../images/logo-horizontal-color.png";
import horizontalWhite from "../images/logo-horizontal-white.png";

// Full logo: the white version on dark surfaces, the coloured one on light surfaces (theme-aware via CSS).
export function Logo({ onDark = false, height = 34 }) {
  if (onDark) return <img className="logo" src={horizontalWhite} alt="GWC Data.ai" style={{ height }} />;
  return (
    <>
      <img className="logo logo-light" src={horizontalColor} alt="GWC Data.ai" style={{ height }} />
      <img className="logo logo-dark" src={horizontalWhite} alt="" aria-hidden="true" style={{ height }} />
    </>
  );
}

// The symbol only, for badges and avatars (sits on a coloured background).
export function LogoMark({ size = 20 }) {
  return <img className="logo-mark" src={markWhite} alt="" aria-hidden="true" style={{ width: size }} />;
}
