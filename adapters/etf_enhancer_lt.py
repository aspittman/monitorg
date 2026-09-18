from adapters.base import Adapter


class ETFEnhancerLT(Adapter):
    def read(self):
        data = self.result('logs/live_portfolio_history.csv', 'logs/live_positions.csv')
        data.history_reliable = False
        data.warnings.extend([
            'logs/trades.csv and portfolio_history.csv are backtest output, not actual executions.',
            'live_positions.csv and live_portfolio_history.csv cover the shared account; bot ownership is unknown.',
            'No bot-specific durable fill ledger or unique client-order prefix was found.'
        ])
        return data
