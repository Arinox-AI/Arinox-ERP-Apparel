import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn's class merger. Every component in src/components/ui uses it. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
