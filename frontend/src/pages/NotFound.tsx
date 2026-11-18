import { Link } from 'react-router-dom';
import { Button, EmptyState } from '../components/ui';

export function NotFoundPage() {
  return (
    <div className="p-8">
      <EmptyState title="Page not found" action={<Link to="/"><Button variant="primary">Go to dashboard</Button></Link>}>
        The page you requested does not exist.
      </EmptyState>
    </div>
  );
}
