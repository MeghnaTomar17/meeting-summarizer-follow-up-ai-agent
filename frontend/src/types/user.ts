/**
 * Purpose: TypeScript types for user and auth.
 * Service ownership: Frontend.
 */

export interface User {
  id: string;
  email: string;
  fullName?: string;
}
