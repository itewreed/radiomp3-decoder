"""Reed-Solomon over GF(2^8) with the parameters of the Megaradio.mp3 player.

The player uses Henry Minsky's "rscode" library with 28 parity bytes:
primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D), generator roots
alpha^1 .. alpha^28, message bytes first, coefficient 0 is the highest
power. This module produces byte-identical parity (checked against the
original code, see tests) and adds erasure decoding, which the player
did not use.
"""

PRIM = 0x11D
NPAR = 28
FCR = 1

EXP = [0] * 512
LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        EXP[i] = x
        LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= PRIM
    for i in range(255, 512):
        EXP[i] = EXP[i - 255]


_init_tables()


class ReedSolomonError(Exception):
    pass


def gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def gf_div(a, b):
    if b == 0:
        raise ZeroDivisionError
    if a == 0:
        return 0
    return EXP[(LOG[a] + 255 - LOG[b]) % 255]


def gf_pow(a, n):
    return EXP[(LOG[a] * n) % 255]


def gf_inverse(a):
    return EXP[255 - LOG[a]]


def poly_scale(p, x):
    return [gf_mul(c, x) for c in p]


def poly_add(p, q):
    r = [0] * max(len(p), len(q))
    for i, c in enumerate(p):
        r[i + len(r) - len(p)] = c
    for i, c in enumerate(q):
        r[i + len(r) - len(q)] ^= c
    return r


def poly_mul(p, q):
    r = [0] * (len(p) + len(q) - 1)
    for j, b in enumerate(q):
        if b == 0:
            continue
        lb = LOG[b]
        for i, a in enumerate(p):
            if a:
                r[i + j] ^= EXP[LOG[a] + lb]
    return r


def poly_eval(p, x):
    y = p[0]
    if x == 0:
        return p[-1]
    lx = LOG[x]
    for c in p[1:]:
        y = (EXP[LOG[y] + lx] if y else 0) ^ c
    return y


def generator_poly(nsym=NPAR, fcr=FCR):
    g = [1]
    for i in range(nsym):
        g = poly_mul(g, [1, gf_pow(2, i + fcr)])
    return g


GEN = generator_poly()


def encode(msg, nsym=NPAR):
    """Return the nsym parity bytes for msg."""
    gen = GEN if nsym == NPAR else generator_poly(nsym)
    buf = list(msg) + [0] * nsym
    for i in range(len(msg)):
        coef = buf[i]
        if coef:
            lc = LOG[coef]
            for j in range(1, len(gen)):
                if gen[j]:
                    buf[i + j] ^= EXP[lc + LOG[gen[j]]]
    return bytes(buf[len(msg):])


def syndromes(codeword, nsym=NPAR, fcr=FCR):
    return [0] + [poly_eval(codeword, gf_pow(2, i + fcr)) for i in range(nsym)]


def _errata_locator(coef_pos):
    loc = [1]
    for p in coef_pos:
        loc = poly_mul(loc, poly_add([1], [gf_pow(2, p), 0]))
    return loc


def _error_evaluator(synd, err_loc, nsym):
    rem = poly_mul(synd, err_loc)
    return rem[len(rem) - (nsym + 1):]


def _correct_errata(msg, synd, err_pos, fcr=FCR):
    coef_pos = [len(msg) - 1 - p for p in err_pos]
    err_loc = _errata_locator(coef_pos)
    err_eval = _error_evaluator(synd[::-1], err_loc, len(err_loc) - 1)[::-1]
    xs = [gf_pow(2, -(255 - p) % 255) for p in coef_pos]
    out = list(msg)
    for i, xi in enumerate(xs):
        xi_inv = gf_inverse(xi)
        prime = 1
        for j, xj in enumerate(xs):
            if j != i:
                prime = gf_mul(prime, 1 ^ gf_mul(xi_inv, xj))
        if prime == 0:
            raise ReedSolomonError("could not find error magnitude")
        y = poly_eval(err_eval[::-1], xi_inv)
        y = gf_mul(gf_pow(xi, (1 - fcr) % 255), y)
        out[err_pos[i]] ^= gf_div(y, prime)
    return out


def _forney_syndromes(synd, pos, nmess):
    fsynd = list(synd[1:])
    for p in pos:
        x = gf_pow(2, nmess - 1 - p)
        for j in range(len(fsynd) - 1):
            fsynd[j] = gf_mul(fsynd[j], x) ^ fsynd[j + 1]
    return fsynd


def _error_locator(synd, nsym, erase_count=0):
    err_loc = [1]
    old_loc = [1]
    for i in range(nsym - erase_count):
        delta = synd[i]
        for j in range(1, len(err_loc)):
            delta ^= gf_mul(err_loc[-(j + 1)], synd[i - j])
        old_loc = old_loc + [0]
        if delta:
            if len(old_loc) > len(err_loc):
                new_loc = poly_scale(old_loc, delta)
                old_loc = poly_scale(err_loc, gf_inverse(delta))
                err_loc = new_loc
            err_loc = poly_add(err_loc, poly_scale(old_loc, delta))
    while err_loc and err_loc[0] == 0:
        del err_loc[0]
    errs = len(err_loc) - 1
    if (errs - erase_count) * 2 + erase_count > nsym:
        raise ReedSolomonError("too many errors")
    return err_loc


def _find_errors(err_loc, nmess):
    errs = len(err_loc) - 1
    pos = [nmess - 1 - i for i in range(nmess) if poly_eval(err_loc, gf_pow(2, i)) == 0]
    if len(pos) != errs:
        raise ReedSolomonError("could not locate errors")
    return pos


def decode(codeword, erase_pos=None, nsym=NPAR):
    """Correct a codeword (message + parity) in place semantics.

    Returns (corrected bytes, number of corrected symbols). Raises
    ReedSolomonError if the codeword cannot be corrected. Up to nsym/2
    unknown errors, or up to nsym erasures (known bad positions), or any
    mix with 2*errors + erasures <= nsym can be corrected.
    """
    msg = list(codeword)
    erase_pos = sorted(set(erase_pos or []))
    if len(erase_pos) > nsym:
        raise ReedSolomonError("too many erasures")
    for p in erase_pos:
        msg[p] = 0
    synd = syndromes(msg, nsym)
    if max(synd) == 0:
        return bytes(msg), _count_diff(codeword, msg)
    fsynd = _forney_syndromes(synd, erase_pos, len(msg))
    err_loc = _error_locator(fsynd, nsym, len(erase_pos))
    err_pos = _find_errors(err_loc[::-1], len(msg))
    msg = _correct_errata(msg, synd, erase_pos + err_pos)
    if max(syndromes(msg, nsym)) != 0:
        raise ReedSolomonError("correction failed")
    return bytes(msg), _count_diff(codeword, msg)


def check(codeword, nsym=NPAR):
    return max(syndromes(codeword, nsym)) == 0


def _count_diff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)
