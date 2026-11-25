// Adapted from shadcn/ui Button (MIT, https://github.com/shadcn-ui/ui).
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import type { ComponentProps } from 'react';
import { twMerge } from 'tailwind-merge';

const variants = cva('button', {
  variants: {
    variant: { default: 'button-primary', ghost: 'button-ghost', outline: 'button-outline' },
  },
  defaultVariants: { variant: 'default' },
});
export function Button({
  className,
  variant,
  asChild = false,
  ...props
}: ComponentProps<'button'> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : 'button';
  return <Component className={twMerge(clsx(variants({ variant }), className))} {...props} />;
}
