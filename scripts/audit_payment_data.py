"""
Payment Data Audit and Repair Script

This script validates payment data integrity and fixes inconsistencies.

Usage:
    python -m scripts.audit_payment_data --check-only
    python -m scripts.audit_payment_data --fix
    python -m scripts.audit_payment_data --fix --transaction-id 123

Safety:
    - Always run with --check-only first
    - Backups recommended before --fix
    - Logs all changes to audit.log
"""
import asyncio
import argparse
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.services.payment_state_calculator import PaymentStateCalculator
from src.config import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audit_payment_data.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PaymentDataAuditor:
    """Audits and repairs payment data integrity."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.issues_found = []
        self.fixes_applied = []

    async def check_event_sum_mismatch(self) -> list[dict]:
        """
        Find transactions where SUM(events.amount) != transaction.paid_amount.

        Returns:
            List of dicts with transaction_id, event_sum, paid_amount, diff
        """
        logger.info("Checking for event sum mismatches...")

        query = """
            SELECT
                ctd.id as transaction_id,
                ctd.client_code,
                ctd.reys as flight,
                COALESCE(SUM(cpe.amount), 0) as event_sum,
                COALESCE(ctd.paid_amount, 0) as paid_amount,
                COALESCE(SUM(cpe.amount), 0) - COALESCE(ctd.paid_amount, 0) as diff
            FROM client_transaction_data ctd
            LEFT JOIN client_payment_events cpe ON cpe.transaction_id = ctd.id
            GROUP BY ctd.id, ctd.client_code, ctd.reys, ctd.paid_amount
            HAVING ABS(COALESCE(SUM(cpe.amount), 0) - COALESCE(ctd.paid_amount, 0)) > 0.01
            ORDER BY ABS(COALESCE(SUM(cpe.amount), 0) - COALESCE(ctd.paid_amount, 0)) DESC
        """

        result = await self.session.execute(query)
        rows = result.fetchall()

        mismatches = []
        for row in rows:
            mismatch = {
                'transaction_id': row.transaction_id,
                'client_code': row.client_code,
                'flight': row.flight,
                'event_sum': float(row.event_sum),
                'paid_amount': float(row.paid_amount),
                'diff': float(row.diff)
            }
            mismatches.append(mismatch)
            self.issues_found.append(mismatch)

        logger.info(f"Found {len(mismatches)} transactions with mismatched sums")
        return mismatches

    async def check_null_payment_providers(self) -> list[int]:
        """Find payment events with NULL payment_provider."""
        logger.info("Checking for NULL payment_providers...")

        query = """
            SELECT id, transaction_id, amount, payment_type
            FROM client_payment_events
            WHERE payment_provider IS NULL
        """

        result = await self.session.execute(query)
        rows = result.fetchall()

        null_providers = []
        for row in rows:
            null_providers.append({
                'event_id': row.id,
                'transaction_id': row.transaction_id,
                'amount': float(row.amount),
                'payment_type': row.payment_type
            })
            self.issues_found.append({
                'type': 'null_provider',
                'event_id': row.id,
                'transaction_id': row.transaction_id
            })

        logger.warning(f"Found {len(null_providers)} events with NULL payment_provider")
        return null_providers

    async def check_invalid_status_transitions(self) -> list[dict]:
        """Find transactions with invalid status (e.g., paid with remaining > 0)."""
        logger.info("Checking for invalid status transitions...")

        query = """
            SELECT id, client_code, payment_status, remaining_amount
            FROM client_transaction_data
            WHERE (payment_status = 'paid' AND remaining_amount > 0.01)
               OR (payment_status = 'pending' AND paid_amount > 0)
               OR (payment_status = 'partial' AND remaining_amount <= 0)
        """

        result = await self.session.execute(query)
        rows = result.fetchall()

        invalid = []
        for row in rows:
            invalid.append({
                'transaction_id': row.id,
                'client_code': row.client_code,
                'status': row.payment_status,
                'remaining': float(row.remaining_amount)
            })
            self.issues_found.append({
                'type': 'invalid_status',
                'transaction_id': row.id
            })

        logger.warning(f"Found {len(invalid)} transactions with invalid status")
        return invalid

    async def fix_transaction(self, transaction_id: int) -> bool:
        """
        Fix a single transaction by recalculating from events.

        Args:
            transaction_id: Transaction ID to fix

        Returns:
            True if fixed successfully
        """
        try:
            logger.info(f"Fixing transaction {transaction_id}...")

            # Recalculate state
            transaction = await PaymentStateCalculator.recalculate_transaction_payment_state(
                self.session,
                transaction_id,
                lock_row=True
            )

            # Log the fix
            fix_record = {
                'transaction_id': transaction_id,
                'new_paid_amount': float(transaction.paid_amount),
                'new_remaining': float(transaction.remaining_amount),
                'new_status': transaction.payment_status,
                'new_type': transaction.payment_type,
                'timestamp': datetime.now().isoformat()
            }
            self.fixes_applied.append(fix_record)

            logger.info(
                f"Fixed transaction {transaction_id}: "
                f"status={transaction.payment_status}, "
                f"paid={transaction.paid_amount:.2f}, "
                f"remaining={transaction.remaining_amount:.2f}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to fix transaction {transaction_id}: {e}")
            return False

    async def fix_all_mismatches(self, mismatches: list[dict]) -> int:
        """
        Fix all transactions with mismatches.

        Args:
            mismatches: List of mismatch dicts from check_event_sum_mismatch

        Returns:
            Number of transactions fixed
        """
        fixed_count = 0

        for mismatch in mismatches:
            transaction_id = mismatch['transaction_id']
            if await self.fix_transaction(transaction_id):
                fixed_count += 1

        return fixed_count

    async def generate_report(self) -> str:
        """Generate audit report."""
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("PAYMENT DATA AUDIT REPORT")
        report_lines.append("=" * 60)
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")

        report_lines.append(f"Issues Found: {len(self.issues_found)}")
        report_lines.append(f"Fixes Applied: {len(self.fixes_applied)}")
        report_lines.append("")

        if self.issues_found:
            report_lines.append("ISSUES DETAILS:")
            for issue in self.issues_found:
                report_lines.append(f"  - {issue}")

        if self.fixes_applied:
            report_lines.append("")
            report_lines.append("FIXES APPLIED:")
            for fix in self.fixes_applied:
                report_lines.append(f"  - Transaction {fix['transaction_id']}: {fix}")

        report_lines.append("=" * 60)

        return "\n".join(report_lines)


async def main():
    parser = argparse.ArgumentParser(description='Audit and repair payment data')
    parser.add_argument('--check-only', action='store_true', help='Only check, do not fix')
    parser.add_argument('--fix', action='store_true', help='Fix found issues')
    parser.add_argument('--transaction-id', type=int, help='Fix specific transaction only')

    args = parser.parse_args()

    logger.info("Starting payment data audit...")

    # Initialize database
    db_client = DatabaseClient(config.database.database_url)
    async with db_client.get_session() as session:
        auditor = PaymentDataAuditor(session)

        # Run checks
        mismatches = await auditor.check_event_sum_mismatch()
        null_providers = await auditor.check_null_payment_providers()
        invalid_statuses = await auditor.check_invalid_status_transitions()

        # Print summary
        logger.info(f"\nAudit Summary:")
        logger.info(f"  - Event sum mismatches: {len(mismatches)}")
        logger.info(f"  - NULL payment_providers: {len(null_providers)}")
        logger.info(f"  - Invalid statuses: {len(invalid_statuses)}")

        # Apply fixes if requested
        if args.fix:
            if args.transaction_id:
                # Fix specific transaction
                logger.info(f"\nFixing transaction {args.transaction_id}...")
                await auditor.fix_transaction(args.transaction_id)
            else:
                # Fix all mismatches
                logger.info(f"\nFixing {len(mismatches)} transactions...")
                fixed_count = await auditor.fix_all_mismatches(mismatches)
                logger.info(f"Fixed {fixed_count} transactions")

            # Commit changes
            await session.commit()
            logger.info("Changes committed")

        elif args.check_only:
            logger.info("\nCheck-only mode: No fixes applied")

        # Generate report
        report = await auditor.generate_report()
        logger.info(f"\n{report}")

        # Write report to file
        with open(f'audit_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt', 'w') as f:
            f.write(report)

    logger.info("Audit complete")


if __name__ == "__main__":
    asyncio.run(main())
