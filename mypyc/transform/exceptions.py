"""Transform that inserts error checks after opcodes.

When initially building the IR, the code doesn't perform error checks
for exceptions. This module is used to insert all required error checks
afterwards. Each Op describes how it indicates an error condition (if
at all).

We need to split basic blocks on each error check since branches can
only be placed at the end of a basic block.
"""

from __future__ import annotations

from typing import Optional, cast

from mypyc.ir.func_ir import FuncIR
from mypyc.ir.ops import (
    ERR_ALWAYS,
    ERR_FALSE,
    ERR_MAGIC,
    ERR_MAGIC_OVERLAPPING,
    ERR_NEVER,
    NO_TRACEBACK_LINE_NO,
    BasicBlock,
    Branch,
    CallC,
    ComparisonOp,
    Float,
    GetAttr,
    Integer,
    LoadErrorValue,
    Op,
    RegisterOp,
    Return,
    SetAttr,
    TupleGet,
    Value,
)
from mypyc.ir.rtypes import RTuple, bool_rprimitive, is_float_rprimitive
from mypyc.primitives.exc_ops import err_occurred_op
from mypyc.primitives.registry import CFunctionDescription


def insert_exception_handling(ir: FuncIR) -> None:
    # Generate error block if any ops may raise an exception. If an op
    # fails without its own error handler, we'll branch to this
    # block. The block just returns an error value.
    error_label = cast(Optional[BasicBlock], None)
    for block in ir.blocks:
        adjust_error_kinds(block)
        if error_label is None and any(op.can_raise() for op in block.ops):
            error_label = add_default_handler_block(ir)
    if error_label:
        ir.blocks = split_blocks_at_errors(ir.blocks, error_label, ir.traceback_name)


def add_default_handler_block(ir: FuncIR) -> BasicBlock:
    block = BasicBlock()
    ir.blocks.append(block)
    op = LoadErrorValue(ir.ret_type)
    block.ops.append(op)
    block.ops.append(Return(op))
    return block


def split_blocks_at_errors(
    blocks: list[BasicBlock], default_error_handler: BasicBlock, func_name: str | None
) -> list[BasicBlock]:
    new_blocks: list[BasicBlock] = []

    # First split blocks on ops that may raise.
    for block in blocks:
        ops = block.ops
        block.ops = []
        cur_block = block
        new_blocks.append(cur_block)

        # If the block has an error handler specified, use it. Otherwise
        # fall back to the default.
        error_label = block.error_handler or default_error_handler
        block.error_handler = None

        for op in ops:
            target: Value = op
            cur_block.ops.append(op)
            if isinstance(op, RegisterOp) and op.error_kind != ERR_NEVER:
                # Split
                new_block = BasicBlock()
                new_blocks.append(new_block)

                if op.error_kind == ERR_MAGIC:
                    # Op returns an error value on error that depends on result RType.
                    variant = Branch.IS_ERROR
                    negated = False
                elif op.error_kind == ERR_FALSE:
                    # Op returns a C false value on error.
                    variant = Branch.BOOL
                    negated = True
                elif op.error_kind == ERR_ALWAYS:
                    variant = Branch.BOOL
                    negated = True
                    # this is a hack to represent the always fail
                    # semantics, using a temporary bool with value false
                    target = Integer(0, bool_rprimitive)
                elif op.error_kind == ERR_MAGIC_OVERLAPPING:
                    comp = insert_overlapping_error_value_check(cur_block.ops, target)
                    new_block2 = BasicBlock()
                    new_blocks.append(new_block2)
                    branch = Branch(
                        comp,
                        true_label=new_block2,
                        false_label=new_block,
                        op=Branch.BOOL,
                        rare=True,
                    )
                    cur_block.ops.append(branch)
                    cur_block = new_block2
                    target = primitive_call(err_occurred_op, [], target.line)
                    cur_block.ops.append(target)
                    variant = Branch.IS_ERROR
                    negated = True
                else:
                    assert False, "unknown error kind %d" % op.error_kind

                # Void ops can't generate errors since error is always
                # indicated by a special value stored in a register.
                if op.error_kind != ERR_ALWAYS:
                    assert not op.is_void, "void op generating errors?"

                branch = Branch(
                    target, true_label=error_label, false_label=new_block, op=variant, line=op.line
                )
                branch.negated = negated
                if op.line != NO_TRACEBACK_LINE_NO and func_name is not None:
                    branch.traceback_entry = (func_name, op.line)
                cur_block.ops.append(branch)
                cur_block = new_block

    return new_blocks


def primitive_call(desc: CFunctionDescription, args: list[Value], line: int) -> CallC:
    return CallC(
        desc.c_function_name,
        [],
        desc.return_type,
        desc.steals,
        desc.is_borrowed,
        desc.error_kind,
        line,
    )


def adjust_error_kinds(block: BasicBlock) -> None:
    """Infer more precise error_kind attributes for ops.

    We have access here to more information than what was available
    when the IR was initially built.
    """
    for op in block.ops:
        if isinstance(op, GetAttr):
            if op.class_type.class_ir.is_always_defined(op.attr):
                op.error_kind = ERR_NEVER
        if isinstance(op, SetAttr):
            if op.class_type.class_ir.is_always_defined(op.attr):
                op.error_kind = ERR_NEVER


def insert_overlapping_error_value_check(ops: list[Op], target: Value) -> ComparisonOp:
    """Append to ops to check for an overlapping error value."""
    typ = target.type
    if isinstance(typ, RTuple):
        item = TupleGet(target, 0)
        ops.append(item)
        return insert_overlapping_error_value_check(ops, item)
    else:
        errvalue: Value
        if is_float_rprimitive(target.type):
            errvalue = Float(float(typ.c_undefined))
        else:
            errvalue = Integer(int(typ.c_undefined), rtype=typ)
        op = ComparisonOp(target, errvalue, ComparisonOp.EQ)
        ops.append(op)
        return op
