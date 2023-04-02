# summary
# if
# elif
# else

# problem 1: compare two integers supplied by the user
x = int(input("value of x"))
y = int(input("value of y"))
"""
if x < y:
    print(x, "<", y)
if x > y:
    print(x, ">", y)
if x == y:
    print(x, "=", y)"
"""
# how can we simplify this code?
# think about asking the fewest number of questions to get the most info
"""
if x < y:
    print(x, "<", y)
elif x > y:
    print(x, ">", y)
elif x == y:
    print(x, "=", y)
"""
"""
if x < y:
    print(x, "<", y)
elif x > y:
    print(x, ">", y)
else:
    print(x, "=", y)
"""
# prob 2 - Is x equal to y?
# could also use != to ask if x is not equal to y
if x < y or x > y:
    print(x, "does not =", y)
else:
    print(x, "=", y)

# modulo % = the remainder
if x % 2 == 0:
    print("x is even")
else:
    print("x is odd")
