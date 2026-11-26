"""Fitting the logit demand model to daily sales, and an excess-price screen built on it.

With logit demand the share of shoppers who buy from seller i is

    s_i = exp((a_i - p_i) / mu) / (exp(0) + sum over sellers j of exp((a_j - p_j) / mu)),

where a_i is the seller's quality, p_i its price, mu how loyal shoppers are
(the larger, the less they react to price) and the outside option (buying
nothing) has utility 0. Dividing by the share s_0 of shoppers who buy nothing
cancels the denominator, and taking logs gives a straight line in price:

    ln(s_i / s_0) = a_i / mu - p_i / mu.

So a regression of ln(s_i / s_0) on the seller's own price, with one intercept
per seller and a common slope, estimates -1/mu (the slope) and a_i/mu (the
intercepts). This is the standard logit inversion used in empirical
industrial organisation. Prices here are set from yesterday's prices, not from
today's demand, so ordinary least squares is not biased by price responding to
demand shocks.

With the fitted market in hand, the competitive (Nash) and monopoly prices
follow from :func:`quiet_cartel.model.nash_prices` and
:func:`quiet_cartel.model.monopoly_prices`, and the excess price index says
where observed prices sit between them. A regulator could only run this screen
with sales data, which is why it is kept separate from the price-only screens.

This module is Python only (the browser app has no sales data), so it uses
``math.log`` freely; nothing here needs to match the JavaScript bit for bit.
"""

import math

from . import model

__all__ = ['fit_market', 'benchmark', 'calibrate_panel', 'nash_residual', 'competitive_prices',
           'MIN_FIT_DAYS', 'DROP_WARN']

MIN_FIT_DAYS = 5        # fewer usable days than this and the fit is not attempted
DROP_WARN = 0.05        # warn when more than this share of days had to be dropped
NAN = float('nan')


# ------------------------------------------------------------ competitive prices

def nash_residual(prices, quality, cost, outside, mu):
    """Largest gap in the logit first-order condition p_i = c_i + mu / (1 - s_i): zero at an equilibrium."""
    s = model.shares(prices, quality, outside, mu)
    return max(abs(prices[i] - cost[i] - mu / (1 - s[i])) for i in range(len(prices)))


def _best_response(i, prices, quality, cost, outside, mu):
    """Seller i's profit-maximising price against the others' prices, by bisection on its first-order condition.

    g(p) = p - c_i - mu / (1 - s_i(p)) rises with p, is negative at p = c_i + mu
    and positive once p is large, so it has exactly one root.
    """
    trial = list(prices)

    def g(p):
        trial[i] = p
        return p - cost[i] - mu / (1 - model.shares(trial, quality, outside, mu)[i])

    lo, hi = cost[i] + mu, cost[i] + 2 * mu + 1
    while g(hi) < 0:
        hi += hi - lo
    for _ in range(200):
        mid = (lo + hi) / 2
        if g(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return (lo + hi) / 2


def competitive_prices(quality, cost, outside, mu):
    """Competitive (Nash) prices, from ``model.nash_prices`` when it converges, otherwise by best responses.

    ``model.nash_prices`` updates every seller at once (p_i <- c_i + mu / (1 -
    s_i)). With equal sellers that update stays on the symmetric path and
    converges, but with unequal sellers and large shares it is unstable away
    from that path (at the default mu of 0.25 the slope of the update in the
    direction that separates two sellers is about -1.7) and ends in a two-day
    cycle that is not an equilibrium. So the result is checked against the
    first-order conditions, and when it fails, each seller in turn plays its
    exact best response until prices stop moving, which converges because a
    logit seller's best response moves less than one for one with its rivals'
    prices. Returns ``(prices, method)`` with method ``'model'`` or ``'best response'``.
    """
    p = model.nash_prices(quality, cost, outside, mu)
    if nash_residual(p, quality, cost, outside, mu) < 1e-9:
        return p, 'model'
    p = [c + mu for c in cost[:len(quality)]]
    for _ in range(10000):
        change = 0.0
        for i in range(len(p)):
            new = _best_response(i, p, quality, cost, outside, mu)
            change = max(change, abs(new - p[i]))
            p[i] = new
        if change < 1e-13:
            break
    return p, 'best response'


def fit_market(prices_a, prices_b, units_a, units_b, shoppers):
    """Fit the logit demand model to one market's daily prices and sales.

    Each day gives two observations, one per seller: y = ln(s_i / s_0) and its
    own price p_i, with s_i = units_i / shoppers and s_0 = (shoppers - units_a -
    units_b) / shoppers, the share who bought nothing. Days on which any share
    is zero (or there were no shoppers) are dropped, since the log is undefined. Pooled OLS with a common slope b and one intercept c_i per
    seller is solved in closed form: b is the within-seller covariance of price
    and y over the within-seller variance of price, and c_i = mean(y_i) - b *
    mean(p_i).

    Returns a dict with ``usable`` (False when there are too few usable days,
    no price variation, or the slope is not negative, with the reason in
    ``problem``), ``slope`` and ``slopeSe`` (the usual OLS standard error, on
    N - 3 degrees of freedom), ``mu`` = -1/slope with ``muSe`` = slopeSe /
    slope**2 (the delta method: d(-1/b)/db = 1/b**2), ``quality`` = c_i * mu
    per seller, ``intercepts``, ``r2`` (against the overall mean of y),
    ``days`` used, ``dropped`` days, ``note`` (a warning when more than 5% of
    days were dropped, else ``None``) and ``meanPrice`` per seller over every
    day given (used, or not, in the fit).
    """
    T = len(prices_a)
    if not (len(prices_b) == len(units_a) == len(units_b) == len(shoppers) == T):
        raise ValueError('prices, units and shoppers must all cover the same days')
    obs = ([], [])                          # per seller: (price, y) pairs
    for t in range(T):
        n = shoppers[t]
        if not n > 0:
            continue
        # The outside share comes from the count of non-buyers: 1 - sa - sb can leave a rounding
        # crumb such as 1e-17 when every shopper bought something, and its log would swamp the fit.
        u0 = n - units_a[t] - units_b[t]
        sa, sb, s0 = units_a[t] / n, units_b[t] / n, u0 / n
        if sa <= 0 or sb <= 0 or s0 <= 0:
            continue
        l0 = math.log(s0)
        obs[0].append((prices_a[t], math.log(sa) - l0))
        obs[1].append((prices_b[t], math.log(sb) - l0))
    days = len(obs[0])
    fit = {'usable': False, 'problem': None, 'note': None, 'days': days, 'dropped': T - days,
           'meanPrice': [model.mean(prices_a), model.mean(prices_b)],
           'slope': None, 'slopeSe': None, 'mu': None, 'muSe': None,
           'intercepts': None, 'quality': None, 'r2': None}
    if T and (T - days) / T > DROP_WARN:
        # Zero counts are nearly always days on which every shopper bought something. Keeping only the
        # other days over-represents days with unusually many non-buyers when prices were low, which
        # flattens the fitted line (mu too high).
        fit['note'] = ('%d of %d days had a zero share (usually every shopper bought something) and were dropped, '
                       'which biases the fit, usually towards too high a mu' % (T - days, T))
    if days < MIN_FIT_DAYS:
        fit['problem'] = 'only %d day%s with every share above zero' % (days, '' if days == 1 else 's')
        return fit
    means = []
    sxx = sxy = 0.0
    for pairs in obs:
        mp = math.fsum(p for p, _ in pairs) / days
        my = math.fsum(y for _, y in pairs) / days
        means.append((mp, my))
        for p, y in pairs:
            sxx += (p - mp) * (p - mp)
            sxy += (p - mp) * (y - my)
    if not sxx > 1e-12:
        fit['problem'] = 'prices never change, so their effect on sales cannot be measured'
        return fit
    b = sxy / sxx
    intercepts = [my - b * mp for mp, my in means]
    all_y = [y for pairs in obs for _, y in pairs]
    ybar = math.fsum(all_y) / len(all_y)
    ssr = sst = 0.0
    for i, pairs in enumerate(obs):
        for p, y in pairs:
            e = y - intercepts[i] - b * p
            ssr += e * e
            sst += (y - ybar) * (y - ybar)
    df = 2 * days - 3
    se = math.sqrt(ssr / df / sxx)
    fit.update({'slope': b, 'slopeSe': se, 'intercepts': intercepts,
                'r2': 1 - ssr / sst if sst > 0 else NAN})
    if not b < 0:
        fit['problem'] = 'sales do not fall as prices rise (slope %+.3f), so the fit is unusable' % b
        return fit
    mu = -1 / b
    fit.update({'usable': True, 'mu': mu, 'muSe': se / (b * b), 'quality': [c * mu for c in intercepts]})
    return fit


def benchmark(fit, costs):
    """Competitive and monopoly prices of the fitted market, and the excess price index.

    The fitted market has the fitted qualities and mu, the given unit costs and
    an outside option of 0. Competitive prices come from ``model.nash_prices``,
    checked and if need be replaced by :func:`competitive_prices` (reported in
    ``nashMethod``); monopoly prices from ``model.monopoly_prices``. The index
    for each seller is (mean observed price
    - fitted competitive price) / (fitted monopoly price - fitted competitive
    price): 0 means competitive prices, 1 monopoly prices, and values below 0 or
    above 1 are possible. ``excessPrice`` is its average over the two sellers.
    Every value is ``None`` when the fit is unusable or there are no costs.
    """
    out = {'competitive': None, 'monopoly': None, 'excess': None, 'excessPrice': None, 'nashMethod': None}
    if not fit['usable'] or costs is None:
        return out
    q, mu = fit['quality'], fit['mu']
    # Fitted qualities are never exactly equal, which is where model.nash_prices can fail: see competitive_prices.
    pn, method = competitive_prices(q, costs, 0, mu)
    pm = model.monopoly_prices(q, costs, 0, mu)
    out['nashMethod'] = method
    excess = []
    for i in range(2):
        gap = pm[i] - pn[i]
        excess.append((fit['meanPrice'][i] - pn[i]) / gap if gap > 0 else NAN)
    out.update({'competitive': pn, 'monopoly': pm, 'excess': excess, 'excessPrice': model.mean(excess)})
    return out


def calibrate_panel(panel, truth=None):
    """Fit demand and compute the excess price index for every market of a panel with sales.

    ``panel`` comes from :func:`quiet_cartel.screening.read_panel` and must
    have ``shoppers`` and ``units``; markets without costs get a fit but no
    index. When ``truth`` (from :func:`quiet_cartel.screening.read_truth`) is
    given, the result also reports, over markets with a usable fit, the mean
    absolute error and mean error of the fitted mu against the true one, the
    mean absolute error of the fitted competitive price against the true one
    when the truth file has it, and how well the excess index ranks markets
    (ROC AUC for both targets, through :func:`quiet_cartel.screening.evaluate`).
    """
    from . import screening     # imported here: screening does not need this module

    markets = []
    for m, d in panel.items():
        if 'units' not in d or 'shoppers' not in d:
            raise ValueError('market %s has no sales data (needs shoppers, units_a and units_b columns)' % m)
        fit = fit_market(d['prices'][0], d['prices'][1], d['units'][0], d['units'][1], d['shoppers'])
        bm = benchmark(fit, d['cost'])
        markets.append({'market': m, 'fit': fit, 'benchmark': bm, 'excessPrice': bm['excessPrice'],
                        'scores': {'excessPrice': bm['excessPrice']}})
    out = {'markets': markets, 'usable': sum(1 for r in markets if r['fit']['usable']), 'truth': None}
    if truth is None:
        return out
    errors, comp_errors = [], []
    for r in markets:
        t = truth.get(r['market'])
        if t is None:
            continue
        if 'mu' in t:
            r['trueMu'] = t['mu']
            if r['fit']['usable']:
                errors.append(r['fit']['mu'] - t['mu'])
        if 'competitive_price' in t and r['benchmark']['competitive'] is not None:
            comp_errors.append(model.mean(r['benchmark']['competitive']) - t['competitive_price'])
    summary = {
        'compared': len(errors),
        'muMae': model.mean([abs(e) for e in errors]) if errors else None,
        'muBias': model.mean(errors) if errors else None,
        'competitiveMae': model.mean([abs(e) for e in comp_errors]) if comp_errors else None,
        'evaluation': None,
    }
    if any(r['excessPrice'] is not None for r in markets) and any(r['market'] in truth for r in markets):
        summary['evaluation'] = screening.evaluate({'markets': markets}, truth)
    out['truth'] = summary
    return out
