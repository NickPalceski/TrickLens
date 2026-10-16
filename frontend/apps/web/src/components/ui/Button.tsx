import type { ButtonHTMLAttributes } from 'react';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'ghost' | 'azure' | 'danger' | 'ghost-danger';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'md' | 'sm';
  block?: boolean;
}

/**
 * primary: brown in light, yellow in dark (the main action on a screen).
 * azure: social actions (Follow, Approve). danger: destructive actions.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  block = false,
  className,
  type,
  ...rest
}: ButtonProps) {
  const cls = [styles.button, styles[variant], size === 'sm' && styles.sm, block && styles.block, className]
    .filter(Boolean)
    .join(' ');
  return <button type={type ?? 'button'} className={cls} {...rest} />;
}
