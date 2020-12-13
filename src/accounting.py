import uuid
import time
import os.path
import random
import base64
import psycopg2
from fractions import Fraction
from functools import total_ordering
from collections import defaultdict
from enum import Enum
from typing import List, Union, Dict, Any
from Crypto.Hash import SHA3_256
from Crypto.PublicKey import ECC


class AccountId(object):
    """A base class for account identifiers."""

    def __str__(self) -> str:
        """Turns the account ID into a machine-readable string."""
        raise NotImplementedError()

    def readable(self) -> str:
        """Turns the account ID into a human-readable string suitable for
           communication with humans."""
        return str(self)

    def __eq__(self, other):
        return str(self) == str(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(str(self))

    def __lt__(self, other):
        return str(self) < str(other)

    def __le__(self, other):
        return str(self) <= str(other)

    def __ge__(self, other):
        return str(self) >= str(other)

    def __gt__(self, other):
        return str(self) > str(other)


class RedditAccountId(AccountId):
    """An account identifier type for Reddit accounts."""

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __repr__(self):
        return 'RedditAccountId(%r)' % self.value


class DiscordAccountId(AccountId):
    """An account identifier type for Discord mentions."""

    def __init__(self, discord_id):
        self.discord_id = discord_id

    def readable(self):
        return '<@%s>' % self.discord_id

    def __str__(self):
        return 'discord/%s' % self.discord_id

    def __repr__(self):
        return 'DiscordAccountId(%r)' % self.discord_id


class ProxyAccountId(AccountId):
    """An account identifier type for proxy account accesses."""

    def __init__(self, proxy_id, proxied_id):
        """Creates a proxy account identifier."""
        self.proxy_id = proxy_id
        self.proxied_id = proxied_id

    def readable(self):
        return '%s (by proxy: %s)' % (self.proxied_id, self.proxy_id)

    def __str__(self):
        return '%s:%s' % (self.proxy_id, self.proxied_id)

    def __repr__(self):
        return 'ProxyAccountId(%r, %r)' % (self.proxy_id, self.proxied_id)


def parse_atomic_account_id(value: str) -> AccountId:
    """Parses a non-proxy account ID."""
    if value.startswith("<@") and value.endswith(">"):
        if value.startswith("<@!"):
            return DiscordAccountId(value[value.index("!") + 1: -1])
        else:
            return DiscordAccountId(value[value.index("@") + 1: -1])
    elif value.startswith('discord/'):
        return DiscordAccountId(value[len('discord/'):])
    else:
        return RedditAccountId(value)


def parse_account_id(value: Union[str, AccountId]) -> AccountId:
    """Parses an account ID."""
    if isinstance(value, AccountId):
        return value

    elems = value.split(':')
    result = parse_atomic_account_id(elems[-1])
    for proxy in reversed(elems[:-1]):
        result = ProxyAccountId(parse_atomic_account_id(proxy), result)

    return result


def unwrap_proxies(account_id: AccountId) -> AccountId:
    """Unwraps proxy account identifiers, if any, to find the account that
       actually performed a transaction."""
    if isinstance(account_id, ProxyAccountId):
        return unwrap_proxies(account_id.proxied_id)
    else:
        return account_id


@total_ordering
class Authorization(Enum):
    """Defines various levels of authorization for account."""
    CITIZEN = 0
    OFFICER = 1
    ADMIN = 2
    DEVELOPER = 3

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplementedError


class Account(object):
    """An account. Every account has globally unique ID. Additionally, servers have one server-local ID
       per account on the server."""

    def get_uuid(self) -> str:
        """Gets this account's unique identifier."""
        raise NotImplementedError()

    def get_balance(self) -> Fraction:
        """Gets the balance on this account."""
        raise NotImplementedError()

    def is_frozen(self) -> bool:
        """Tells if this account is frozen."""
        raise NotImplementedError()

    def get_authorization(self) -> Authorization:
        """Gets this account's level of authorization."""
        raise NotImplementedError()

    def list_public_keys(self):
        """Produces a list of all public keys associated with this account.
           Every element of the list is a string that corresponds to the contents
           of a PEM file describing an ECC key."""
        raise NotImplementedError()

    def get_proxies(self):
        """Gets all accounts that have been authorized as proxies for this account."""
        raise NotImplementedError()




class RecurringTransfer(object):
    """A recurring transfer."""

    def get_id(self) -> str:
        """Gets the ID for the transfer."""
        raise NotImplementedError()

    def get_author(self) -> Account:
        """Gets the account that authorized the transfer."""
        raise NotImplementedError()

    def get_source(self) -> Account:
        """Gets the account from which the money originates."""
        raise NotImplementedError()

    def get_destination(self) -> Account:
        """Gets the account to which the money must go."""
        raise NotImplementedError()

    def get_tick_count(self) -> int:
        """Gets the number of ticks over the course of which the transfer must complete."""
        raise NotImplementedError()

    def get_total_amount(self) -> Fraction:
        """Gets the total amount to transfer."""
        raise NotImplementedError()

    def get_remaining_amount(self) -> Fraction:
        """Gets the remaining amount to transfer."""
        raise NotImplementedError()

    def get_transferred_amount(self) -> Fraction:
        """Gets the amount of money that has already been transferred."""
        return self.get_total_amount() - self.get_remaining_amount()


class Server(object):
    """A server manages a number of accounts that all have the same currency."""

    def open_account(self, id: AccountId, account_uuid=None) -> Account:
        """Opens an empty account with a particular ID. Raises an exception if the account
           already exists. Otherwise returns the newly opened account."""
        raise NotImplementedError()

    def add_account_alias(self, account: Account, alias_id: AccountId):
        """Associates an additional ID with an account."""
        raise NotImplementedError()

    def get_account(self, id: AccountId) -> Account:
        """Gets the account that matches an ID. Raises an exception if there is no such account."""
        raise NotImplementedError()

    def get_accounts(self) -> List[Account]:
        """Gets a list of all accounts on this server."""
        raise NotImplementedError()

    def get_account_from_string(self, id: str) -> Account:
        """Gets the account that matches a string ID. Raises an exception if there is no such account."""
        return self.get_account(parse_account_id(id))

    def get_account_ids(self, account: Account) -> List[AccountId]:
        """Gets an account's local IDs. Raises an exception if the account is not registered here."""
        raise NotImplementedError()

    def get_account_id(self, account: Account) -> AccountId:
        """Gets a representative local account ID. Raises an exception if the account is not registered here."""
        return self.get_account_ids(account)[0]

    def has_account(self, id: AccountId) -> bool:
        """Tests if an account with a particular ID exists on this server."""
        raise NotImplementedError()

    def get_government_account(self) -> Account:
        """Gets the main government account for this server."""
        raise NotImplementedError()

    def list_accounts(self) -> List[Account]:
        """Lists all accounts on this server."""
        raise NotImplementedError()

    def authorize(self, author: AccountId, account: Account, auth_level: Authorization):
        """Makes `author` set `account`'s authorization level to `auth_level`."""
        raise NotImplementedError()

    def set_frozen(self, author: AccountId, account: Account, is_frozen: bool):
        """Freezes or unfreezes `account` on the authority of `author`."""
        raise NotImplementedError()

    def print_money(self, author: AccountId, account: Account, amount: Fraction):
        """Prints `amount` of money on the authority of `author` and deposits it in `account`."""
        raise NotImplementedError()

    def add_public_key(self, account: Account, key):
        """Associates a public key with an account. The key must be an ECC key."""
        raise NotImplementedError()

    def add_proxy(self, author: AccountId, account: Account, proxied_account: Account):
        """Makes `account` a proxy for `proxied_account`."""
        raise NotImplementedError()

    def remove_proxy(self, author: AccountId, account: Account, proxied_account: Account) -> bool:
        """Ensures that `account` is not a proxy for `proxied_account`. Returns
           `False` is `account` was not a proxy for `procied_account`;
           otherwise, `True`."""
        raise NotImplementedError()

    def get_recurring_transfer(self, id: str) -> RecurringTransfer:
        """Gets a recurring transfer based on its ID."""
        raise NotImplementedError()

    def list_recurring_transfers(self):
        """Produces a list of all recurring transfers."""
        raise NotImplementedError()

    def create_recurring_transfer(
            self,
            author: AccountId,
            source: Account,
            destination: Account,
            total_amount: Fraction,
            tick_count: int) -> RecurringTransfer:
        """Creates and registers a new recurring transfer, i.e., a transfer that is spread out over
           many ticks. The transfer is authorized by `author` and consists of `total_amount` being
           transferred from `source` to `destination` over the course of `tick_count` ticks. A tick
           is a server-defined timespan."""
        raise NotImplementedError()

    def notify_tick_elapsed(self, tick_timestamp=None):
        """Notifies the server that a tick has elapsed."""
        raise NotImplementedError()

    def transfer(self, author: AccountId, source: Account, destination: Account, amount: Fraction):
        """Transfers a particular amount of money from one account on this server to another on
           the authority of `author`. `author`, `destination` and `amount` are `Account` objects.
           This action must not complete successfully if the transfer cannot be performed."""
        raise NotImplementedError()

    def can_transfer(self, source: Account, destination: Account, amount: Fraction) -> bool:
        """Tells if a particular amount of money can be transferred from one account on this
           server to another. `destination` and `amount` are both `Account` objects."""
        return amount > 0 and \
               source.get_balance() - amount >= 0 and \
               not source.is_frozen() and \
               not destination.is_frozen()


class InMemoryServer(Server):
    """A server that maintains accounts in memory. Nothing is persistent.
       This server implementation can be used to implement more sophisticated
       (persistent) servers."""

    def __init__(self):
        self.accounts = {}
        self.inv_accounts = defaultdict(list)
        self.gov_account = InMemoryServer.open_account(self, "@government")
        self.gov_account.auth = Authorization.DEVELOPER
        self.recurring_transfers = {}


    def open_account(self, id: AccountId, account_uuid=None):
        """Opens an empty account with a particular ID. Raises an exception if the account
           already exists. Otherwise returns the newly opened account."""
        if self.has_account(id):
            raise Exception("Account already exists.")

        account = InMemoryAccount(account_uuid)
        self.accounts[id] = account
        self.inv_accounts[account].append(id)
        return account

    def delete_account(self, id: AccountId, account_uuid=None):
        if self.has_account(id):
            account = self.accounts[id]
            to_be_deleted = []
            for rec_transfer in self.recurring_transfers:
                if self.recurring_transfers[rec_transfer].get_destination() == account or self.recurring_transfers[rec_transfer].get_source() == account:
                    to_be_deleted.append(rec_transfer)

            for key in to_be_deleted:
                del self.recurring_transfers[key]

            del self.accounts[id]
            del self.inv_accounts[account][0]

            return True

    def add_account_alias(self, account: Account, alias_id: AccountId):
        """Associates an additional ID with an account."""
        self.accounts[alias_id] = account
        self.inv_accounts[account].append(alias_id)

    def get_account(self, id: AccountId) -> Account:
        """Gets the account that matches an ID. Raises an exception if there is no such account."""
        return self.accounts[unwrap_proxies(id)]

    def get_accounts(self) -> List[Account]:
        """Gets a list of all accounts on this server."""
        return list(set(self.accounts.values()))

    def get_account_ids(self, account: Account) -> List[AccountId]:
        """Gets an account's local IDs. Raises an exception if the account is not registered here."""
        return self.inv_accounts[account]

    def has_account(self, id):
        """Tests if an account with a particular ID exists on this server."""
        return unwrap_proxies(id) in self.accounts

    def get_government_account(self):
        """Gets the main government account for this server."""
        return self.gov_account

    def list_accounts(self):
        """Lists all accounts on this server."""
        unique_accounts = set(self.accounts.values())
        return sorted(unique_accounts, key=lambda account: str(self.get_account_id(account)))

    def mark_public(self, author: AccountId, account: Account, new_public: bool):
        """Sets account.public to new_public"""
        account.public = new_public

    def authorize(self, author: AccountId, account: Account, auth_level: Authorization):
        """Makes `author` set `account`'s authorization level to `auth_level`."""
        account.auth = auth_level

    def set_frozen(self, author: AccountId, account: Account, is_frozen: bool):
        """Freezes or unfreezes `account` on the authority of `author`."""
        account.frozen = is_frozen

    def add_public_key(self, account: Account, key):
        """Associates a public key with an account. The key must be an ECC key."""
        account.public_keys.append(key)

    def add_proxy(self, author: AccountId, account: Account, proxied_account: Account):
        """Makes `account` a proxy for `proxied_account`."""
        proxied_account.proxies.add(account)

    def remove_proxy(self, author: AccountId, account: Account, proxied_account: Account) -> bool:
        """Ensures that `account` is not a proxy for `proxied_account`. Returns
           `False` is `account` was not a proxy for `procied_account`;
           otherwise, `True`."""
        prev_in = account in proxied_account.proxies
        if prev_in:
            proxied_account.proxies.remove(account)

        return not prev_in

    def print_money(self, author: AccountId, account: Account, amount: Fraction):
        """Prints `amount` of money on the authority of `author` and deposits it in `account`."""
        account.balance += amount

    def remove_funds(self, author: Account, account: Account, amount: Fraction):
        account.balance -= amount

    def transfer(self, author: AccountId, source: Account, destination: Account, amount: Fraction):
        """Transfers a particular amount of money from one account on this server to another on
           the authority of `author`. `author`, `destination` and `amount` are `Account` objects.
           This action must not complete successfully if the transfer cannot be performed."""
        if not self.can_transfer(source, destination, amount):
            raise Exception("Cannot perform transfer.")

        source.balance -= amount
        destination.balance += amount

    def get_recurring_transfer(self, id: str):
        """Gets a recurring transfer based on its ID."""
        return self.recurring_transfers[id]

    def list_recurring_transfers(self):
        """Produces a list of all recurring transfers."""
        return self.recurring_transfers.values()

    def create_recurring_transfer(self, author: AccountId, source, destination, total_amount, tick_count,
                                  transfer_id=None):
        """Creates and registers a new recurring transfer, i.e., a transfer that is spread out over
           many ticks. The transfer is authorized by `author` and consists of `total_amount` being
           transferred from `source` to `destination` over the course of `tick_count` ticks. A tick
           is a server-defined timespan."""
        rec_transfer = InMemoryRecurringTransfer(author, source, destination, total_amount, tick_count, total_amount,
                                                 transfer_id)
        self.recurring_transfers[rec_transfer.get_id()] = rec_transfer
        return rec_transfer

    def notify_tick_elapsed(self, tick_timestamp=None):
        """Notifies the server that a tick has elapsed."""
        finished_transfers = set()
        for id in self.recurring_transfers:
            transfer = self.recurring_transfers[id]
            per_tick = transfer.get_total_amount() / transfer.get_tick_count()
            if transfer.get_remaining_amount() <= 0:
                finished_transfers.add(id)
            elif transfer.get_remaining_amount() >= per_tick:
                if self.can_transfer(transfer.get_source(), transfer.get_destination(), per_tick):
                    self.perform_recurring_transfer(transfer, per_tick)
            else:
                remaining = transfer.get_total_amount()
                if self.can_transfer(transfer.get_source(), transfer.get_destination(), remaining):
                    self.perform_recurring_transfer(transfer, remaining)
                    finished_transfers.add(id)

        # Delete finished transfers.
        for id in finished_transfers:
            del self.recurring_transfers[id]

    def perform_recurring_transfer(self, transfer, amount):
        InMemoryServer.transfer(
            self,
            transfer.get_author(),
            transfer.get_source(),
            transfer.get_destination(),
            amount)
        transfer.remaining_amount -= amount


class InMemoryAccount(Account):
    """An in-memory account data structure."""

    def __init__(self, account_uuid=None):
        """Initializes an in-memory account."""
        self.uuid = account_uuid if account_uuid is not None else str(
            uuid.uuid4())
        self.balance = 0
        self.frozen = False
        self.public = False
        self.auth = Authorization.CITIZEN
        self.public_keys = []
        self.proxies = set()

    def set_balance(self, bal):
        self.balance = bal

    def get_uuid(self):
        """Gets this account's unique identifier."""
        return self.uuid

    def get_balance(self):
        """Gets the balance on this account."""
        return self.balance

    def is_frozen(self):
        """Tells if this account is frozen."""
        return self.frozen

    def get_authorization(self):
        """Gets this account's level of authorization."""
        return self.auth

    def list_public_keys(self):
        """Produces a list of all public keys associated with this account.
           Every element of the list is an ECC key."""
        return self.public_keys

    def get_proxies(self) -> List[Account]:
        """Gets all accounts that have been authorized as proxies for this account."""
        return list(self.proxies)


class InMemoryRecurringTransfer(RecurringTransfer):
    """An in-memory description of a recurring transfer."""

    def __init__(self, author: AccountId, source: Account, destination: Account, total_amount, tick_count, remaining_amount, transfer_id=None):
        """Initializes an in-memory recurring transfer."""
        self.uuid = transfer_id if transfer_id is not None else str(
            uuid.uuid4())
        self.author = author
        self.source = source
        self.destination = destination
        self.total_amount = total_amount
        self.tick_count = tick_count
        self.remaining_amount = remaining_amount

    def get_id(self):
        """Gets this transfer's ID."""
        return self.uuid

    def get_author(self) -> AccountId:
        """Gets the account ID that authorized the transfer."""
        return self.author

    def get_source(self) -> Account:
        """Gets the account from which the money originates."""
        return self.source

    def get_destination(self) -> Account:
        """Gets the account to which the money must go."""
        return self.destination

    def get_tick_count(self):
        """Gets the number of ticks over the course of which the transfer must complete."""
        return self.tick_count

    def get_total_amount(self):
        """Gets the total amount to transfer."""
        return self.total_amount

    def get_remaining_amount(self):
        """Gets the remaining amount to transfer."""
        return self.remaining_amount


def compute_hash(previous_hash, elements):
    """Computes the SHA3-256 hash digest of a previous hash and a list of strings."""
    hash_obj = SHA3_256.new(previous_hash)
    for item in elements:
        hash_obj.update(item.encode('utf-8'))
    return hash_obj


def generate_salt_and_hash(previous_hash, elements, zero_count):
    """Generates a salt, hash pair with the appropriate number of leading zeros."""
    while True:
        salt = str(random.randint(1, 1000000))
        hash_obj = SHA3_256.new(previous_hash)
        hash_obj.update(salt.encode('utf-8'))
        for item in elements:
            hash_obj.update(item.encode('utf-8'))
        if has_leading_zeros(hash_obj.hexdigest(), zero_count):
            return (salt, hash_obj)


def has_leading_zeros(hexdigest, zero_count):
    """Checks if a hex digest has at least `zero_count` leading zero bits."""
    i = 0
    for _ in range(zero_count // 4):
        if hexdigest[i] != '0':
            return False
        i += 1

    rem = zero_count % 4
    if rem > 0:
        digit = int(hexdigest[i], 16)
        if rem == 1:
            return digit < 8
        elif rem == 2:
            return digit < 4
        elif rem == 3:
            return digit < 2

    return True


def create_initial_ledger_entries(entries, leading_zero_count=12, initial_hash=b''):
    """Creates an initial ledger by annotating hashless ledger entries with hashes and salts.
       `entries` is a list of unannotated ledger lines. A modified list of ledger lines is returned."""
    last_hash = initial_hash
    results = []
    for line in entries:
        if not line.strip():
            results.append(line)
            continue

        elems = line.split()
        salt, line_hash = generate_salt_and_hash(last_hash, elems, leading_zero_count)
        results.append(' '.join([line_hash.hexdigest(), salt] + elems))
        last_hash = line_hash.digest()

    return results


def strip_ledger_hashes_and_salts(entries):
    """Strips hashes and salts from ledger entries."""
    return [
        ' '.join(entry.split()[2:])
        for entry in entries
    ]


def rewrite_ledger(source_path, destination_path, func):
    """Rewrites a ledger by reading it from a source path, applying a function to it and
       writing it to a destination path."""
    with open(source_path, 'r') as f:
        lines = f.readlines()

    lines = func(lines)

    with open(destination_path, 'w') as f:
        f.writelines(line + '\n' for line in lines)


def create_initial_ledger(unannotated_ledger_path, result_path, leading_zero_count=12, initial_hash=b''):
    """Creates an initial ledger by reading the unannotated ledger at `unannoted_ledger_path`,
       annotating every line with a hash and a salt and then writing the result to
       `result_path`."""
    return rewrite_ledger(
        unannotated_ledger_path,
        result_path,
        lambda lines: create_initial_ledger_entries(lines, leading_zero_count, initial_hash))


class WealthTaxBracket:
    """Tax Bracket Object used to represent wealth tax brackets so they can be easily modified"""

    def __init__(self, start, end, rate, exempt_prefixes=None):
        if exempt_prefixes is None:
            exempt_prefixes = ['&', '@']  # default prefixes for government and non-profits
        self.start = start
        self.end = end
        self.tax_rate = rate
        self.exempt_prefixes = exempt_prefixes

    def set_rate(self, rate):
        # sets tax rate
        self.tax_rate = rate

    def add_exempt_prefix(self, prefix):
        # adds exempt prefixes
        self.exempt_prefixes.append(prefix)

    def get_rate(self):
        # returns tax rate for bracket object
        return self.tax_rate

    def set_end(self, end):
        # sets the end of the starting
        self.end = end

    def set_start(self, start):
        self.start = start

    def get_start(self):
        return self.start

    def get_end(self):
        return self.end

    def get_tax(self, account):
        bal = account.get_balance()
        if bal < self.start:
            return 0
        elif self.end is None or bal <= self.end:
            tax_amount = round(((bal - self.start) / 100) * self.tax_rate)
            return tax_amount
        elif bal > self.end:
            tax_amount = round(((self.end - self.start) / 100) * self.tax_rate)
            return tax_amount


class TaxException(Exception):
    pass


class TaxMan:

    def __init__(self, server, tax_regularity=28, auto_tax=False):
        self.tax_brackets = {}
        self.ticks_till_tax = tax_regularity
        self.ticks_till_tax_tmp = self.ticks_till_tax
        self.server = server
        self.autoTax = auto_tax

    def get_bracket(self, name):
        return self.tax_brackets[name]

    def add_tax_bracket(self, min_amount, max_amount, rate, name):
        self.tax_brackets[name] = WealthTaxBracket(min_amount, max_amount, rate)

    def remove_tax_bracket(self, name):
        try:
            del self.tax_brackets[name]
        except KeyError as e:
            raise TaxException("That Account Doesn't Exist SMH")

    def force_ticks(self, amount=1):
        """Only works temporarily is purely for testing purposes"""
        if not self.autoTax:
            return
        self.ticks_till_tax_tmp -= amount
        if self.ticks_till_tax_tmp <= 0 and self.autoTax:
            self.tax()
        return

    def tick(self, from_ledger=False):
        if not self.autoTax:
            return
        self.ticks_till_tax_tmp -= 1
        if self.ticks_till_tax_tmp <= 0:
            self.ticks_till_tax_tmp = self.ticks_till_tax
            if not from_ledger:
                self.tax()
        return

    def toggle_auto_tax(self) -> bool:
        self.autoTax = not self.autoTax
        return self.autoTax

    def get_bracket_value(self, bracket=None):
        value = 0
        if bracket is not None:
            brackets = [bracket]
        else:
            brackets = self.tax_brackets.keys()

        for key in brackets:
            for account in self.server.list_accounts():
                if self.server.get_account_id(account).startswith(
                    tuple(self.tax_brackets[key].exempt_prefixes)): continue
                value += self.tax_brackets[key].get_tax(account)

        return value

    def tax(self):
        self.ticks_till_tax_tmp = self.ticks_till_tax
        i = 0
        for tax_bracket in self.tax_brackets:
            for account in self.server.list_accounts():
                i += 1

                if self.server.get_account_id(account).startswith(
                    tuple(self.tax_brackets[tax_bracket].exempt_prefixes)): continue
                tax_amount = self.tax_brackets[tax_bracket].get_tax(account)
                if tax_amount != 0:
                    self.server.transfer('@government', account, self.server.get_government_account(), tax_amount)
        return


class LedgerServer(InMemoryServer):
    """A server implementation that logs every action in a ledger.
       The ledger can be read to reconstruct the state of the server."""

    def __init__(self, ledger_path, leading_zero_count=12):
        """Initializes a ledger-based server."""
        super().__init__()
        self.taxObject = TaxMan(self)
        self.last_tick_timestamp = time.time()
        self.last_hash = b''
        self.ledger_path = ledger_path
        self.leading_zero_count = leading_zero_count
        if os.path.isfile(ledger_path):
            self._read_ledger(ledger_path)
        self.ledger_file = open(ledger_path, 'a')

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        """Closes the server's underlying ledger file."""
        self.ledger_file.close()

    def _read_ledger(self, ledger_path):
        """Reads a ledger at a particular path."""
        with open(ledger_path, 'r') as f:
            lines = f.readlines()
            f.close()

        for line_num, line in enumerate(lines):
            if line.isspace() or line == '':
                continue

            elems = line.split()
            hash_value = elems[0]
            expected_hash = compute_hash(self.last_hash, elems[1:])

            if expected_hash.hexdigest() != hash_value:
                raise Exception(
                    "Line %s: ledger hash value %s for '%s' does not match expected hash value %s." % (
                        line_num + 1, hash_value, ' '.join(elems[1:]), expected_hash.hexdigest()))
            elif not has_leading_zeros(hash_value, self.leading_zero_count):
                raise Exception(
                    "Line %s: hash value does not have at least %s leading zeros." % (
                        line_num + 1, self.leading_zero_count))

            self.last_hash = expected_hash.digest()

            timestamp = float(elems[2])
            elems = elems[3:]
            cmd = elems[0]
            if cmd == 'open':
                super().open_account(elems[1], elems[2])
            elif cmd == 'transfer':
                super().transfer(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    self.get_account_from_string(elems[3]),
                    Fraction(elems[4]))
            elif cmd == 'authorize':
                super().authorize(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    Authorization[elems[3]])
            elif cmd == 'set-frozen':
                super().set_frozen(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    elems[3] == 'True')
            elif cmd == 'print-money':
                super().print_money(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    Fraction(elems[3])
                )
            elif cmd == 'remove-funds':
                super().remove_funds(
                    self.get_account_from_string(elems[1]),
                    self.get_account_from_string(elems[2]),
                    Fraction(elems[3])
                )
            elif cmd == 'perform-recurring-transfer':
                super().perform_recurring_transfer(
                    self.get_recurring_transfer(elems[1]),
                    Fraction(elems[2]))
            elif cmd == 'create-recurring-transfer':
                rec_transfer = super().create_recurring_transfer(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    self.get_account_from_string(elems[3]),
                    Fraction(elems[4]),
                    int(elems[5]),
                    elems[6])
            elif cmd == 'add-public-key':
                key = base64.b64decode(elems[2]).decode('utf-8')
                super().add_public_key(
                    self.get_account_from_string(elems[1]),
                    ECC.import_key(key))
            elif cmd == 'add-proxy':
                super().add_proxy(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    self.get_account_from_string(elems[3]))
            elif cmd == 'remove-proxy':
                super().remove_proxy(
                    parse_account_id(elems[1]),
                    self.get_account_from_string(elems[2]),
                    self.get_account_from_string(elems[3]))
            elif cmd == 'add-alias':
                super().add_account_alias(
                    self.get_account_from_string(elems[1]),
                    parse_account_id(elems[2]))
            elif cmd == 'tick':
                self.last_tick_timestamp = timestamp
                self.taxObject.tick(True)
            elif cmd == 'delete-account':
                super().delete_account(elems[2])
            elif cmd == 'add-tax-bracket':
                self.get_tax_object().add_tax_bracket(int(elems[2]), int(elems[3]) if elems[3] != "None" else None,
                                                      int(elems[4]), str(elems[5]))
            elif cmd == 'remove-tax-bracket':
                self.get_tax_object().remove_tax_bracket(elems[2])
            elif cmd == 'toggle-auto-tax':
                self.get_tax_object().toggle_auto_tax()
            elif cmd == 'force-tax':
                pass
            elif cmd == 'mark-public':
                super().mark_public(parse_account_id(elems[1]), self.get_account_from_string(elems[2]), elems[3] == "True")

            else:
                raise Exception("Unknown ledger command '%s'." % cmd)

    def _ledger_write(self, *args, t=None):
        if t is None:
            t = time.time()
        elems = [str(t)] + ['%d/%d' % (x.numerator, x.denominator) if isinstance(x, Fraction) else str(x) for x in args]
        salt, new_hash = generate_salt_and_hash(self.last_hash, elems, self.leading_zero_count)
        with open(self.ledger_path, 'a') as f:
            f.writelines(' '.join([new_hash.hexdigest(), salt] + elems) + '\n')
            f.close()
        self.last_hash = new_hash.digest()
        return t

    def open_account(self, id, account_uuid=None):
        """Opens an empty account with a particular ID. Raises an exception if the account
           already exists. Otherwise returns the newly opened account."""
        account = super().open_account(id, account_uuid)
        self._ledger_write('open', id, account.get_uuid())
        return account

    def add_account_alias(self, account: Account, alias_id: AccountId):
        """Associates an additional ID with an account."""
        super().add_account_alias(account, alias_id)
        self._ledger_write(
            'add-alias',
            self.get_account_id(account),
            alias_id)

    def mark_public(self, author: AccountId, account: Account, new_public: bool):
        super().mark_public(author, account, new_public)
        self._ledger_write(
            'mark-public',
            author,
            self.get_account_id(account),
            str(new_public)
        )

    def authorize(self, author: AccountId, account, auth_level):
        """Makes `author` set `account`'s authorization level to `auth_level`."""
        result = super().authorize(author, account, auth_level)
        self._ledger_write(
            'authorize',
            author,
            self.get_account_id(account),
            auth_level.name)
        return result

    def set_frozen(self, author: AccountId, account: Account, is_frozen: bool):
        """Freezes or unfreezes `account` on the authority of `author`."""
        super().set_frozen(author, account, is_frozen)
        self._ledger_write(
            'set-frozen',
            author,
            self.get_account_id(account),
            is_frozen)

    def add_public_key(self, account, key):
        """Associates a public key with an account. The key must be an ECC key."""
        super().add_public_key(account, key)
        self._ledger_write(
            'add-public-key',
            self.get_account_id(account),
            base64.b64encode(key.export_key(format='PEM').encode('utf-8')).decode('utf-8'))

    def add_proxy(self, author: AccountId, account: Account, proxied_account: Account):
        """Makes `account` a proxy for `proxied_account`."""
        result = super().add_proxy(author, account, proxied_account)
        self._ledger_write(
            'add-proxy',
            author,
            self.get_account_id(account),
            self.get_account_id(proxied_account))
        return result

    def delete_account(self, author: AccountId, account: AccountId):
        result = super().delete_account(account)
        self._ledger_write(
            'delete-account',
            author,
            account
        )
        return result

    def get_tax_object(self):
        return self.taxObject

    def add_tax_bracket(self, author: AccountId, start, end, rate, name):
        self.get_tax_object().add_tax_bracket(start, end, rate, name)
        self._ledger_write(
            'add-tax-bracket',
            author,
            str(start),
            str(end),
            str(rate),
            name
        )

    def remove_tax_bracket(self, author: AccountId, name):
        self.get_tax_object().remove_tax_bracket(name)
        self._ledger_write(
            'remove-tax-bracket',
            author,
            name
        )

    def get_tax_brackets(self) -> dict:
        return self.get_tax_object().tax_brackets

    def force_tax(self, author):
        self.get_tax_object().tax()
        self._ledger_write(
            'force-tax',
            author
        )

    def get_bracket_value(self, bracket=None) -> int:
        return self.get_tax_object().get_bracket_value(bracket=bracket)

    def toggle_auto_tax(self, author) -> bool:
        ans = self.get_tax_object().toggle_auto_tax()
        self._ledger_write(
            'toggle-auto-tax',
            author
        )
        return ans

    def add_exempt_prefix(self, author: AccountId, prefix, tax_group):
        self.get_tax_object().get_bracket(tax_group)
        self._ledger_write(
            'add-exempt-prefix'
        )

    def remove_proxy(self, author: AccountId, account: Account, proxied_account: Account) -> bool:
        """Ensures that `account` is not a proxy for `proxied_account`. Returns
           `False` is `account` was not a proxy for `procied_account`;
           otherwise, `True`."""
        result = super().remove_proxy(author, account, proxied_account)
        self._ledger_write(
            'remove-proxy',
            author,
            self.get_account_id(account),
            self.get_account_id(proxied_account))
        return result

    def print_money(self, author: AccountId, account, amount: Fraction):
        """Prints `amount` of money on the authority of `author` and deposits it in `account`."""
        super().print_money(author, account, amount)
        self._ledger_write(
            'print-money',
            author,
            self.get_account_id(account),
            amount)

    def remove_funds(self, author, account, amount: Fraction):
        """Removes `amount` from `account` with `author`'s authority"""
        super().remove_funds(author, account, amount)
        self._ledger_write(
            'remove-funds',
            self.get_account_id(author),
            self.get_account_id(account),
            amount
        )

    def transfer(self, author: AccountId, source, destination, amount: Fraction):
        """Transfers a particular amount of money from one account on this server to another on
           the authority of `author`. `author`, `destination` and `amount` are `Account` objects.
           This action must not complete successfully if the transfer cannot be performed."""
        result = super().transfer(author, source, destination, amount)
        self._ledger_write(
            'transfer',
            author,
            self.get_account_id(source),
            self.get_account_id(destination),
            amount)
        return result

    def notify_tick_elapsed(self, tick_timestamp=None):
        """Notifies the server that a tick has elapsed."""
        super().notify_tick_elapsed()
        self.taxObject.tick()
        self.last_tick_timestamp = self._ledger_write('tick', t=tick_timestamp)

    def create_recurring_transfer(self, author: AccountId, source, destination, total_amount: Fraction, tick_count: int,
                                  transfer_id=None):
        """Creates and registers a new recurring transfer, i.e., a transfer that is spread out over
           many ticks. The transfer is authorized by `author` and consists of `total_amount` being
           transferred from `source` to `destination` over the course of `tick_count` ticks. A tick
           is a server-defined timespan."""
        rec_transfer = super().create_recurring_transfer(author, source, destination, total_amount, tick_count,
                                                         transfer_id)
        self._ledger_write(
            'create-recurring-transfer',
            author,
            self.get_account_id(source),
            self.get_account_id(destination),
            total_amount,
            tick_count,
            rec_transfer.get_id())
        return rec_transfer

    def perform_recurring_transfer(self, transfer, amount):
        super().perform_recurring_transfer(transfer, amount)
        self._ledger_write(
            'perform-recurring-transfer',
            transfer.get_id(),
            amount)


class SQLServer(InMemoryServer):
    def __init__(self, psswd: str, uname: str="taubot",  db: str="taubot", host: str="localhost"):
        super().__init__()
        self.connection = psycopg2.connect(f"dbname='{db}' host='{host}' user='{uname}' password='{psswd}'")
        cursor = self.connection.cursor()
        cursor.execute(open("./src/sql/startup.sql").read())
        cursor.execute("SELECT uuid, name FROM accounts;")
        self.connection.commit()
        account_ids = cursor.fetchall()
        for account_id in account_ids:


    def open_account(self, id: AccountId, account_uuid=None):




class PersistantAccount(InMemoryAccount):
    def __init__(self, uuid: str, connection):
        super().__init__(uuid)
        self.connection = connection

    def set_balance(self, bal):
        super().set_balance(bal)
        cursor = self.connection.cursor()
        cursor.execute("UPDATE accounts SET balance = '%s' WHERE uuid = '%s';", [bal, self.uuid])











