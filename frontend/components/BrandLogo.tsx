type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
  className?: string;
};

const SIZE_CLASS = {
  sm: "w-8 h-8",
  md: "w-12 h-12",
  lg: "w-20 h-20",
} as const;

export function BrandLogo({ size = "md", className = "" }: BrandLogoProps) {
  return (
    <div
      className={`${SIZE_CLASS[size]} rounded-full overflow-hidden bg-white border border-[#444444] shrink-0 ${className}`}
    >
      <img
        src="/mha-logo.jpg"
        alt="MHA Group"
        className="w-full h-full object-contain p-1.5"
      />
    </div>
  );
}
