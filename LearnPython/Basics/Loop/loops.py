# while loop
# keyword continue - stays in loop
# keyword break - breaks you out of loop
# datatype list
# keyword range
# for
# \n
# asking user for specific information - use while loop to create infinite loop. user has to answer correctly to break out of loop
i = 0  # iniialize i with a value
while i != 3:  # use keyword while to start while loop
    print("meow")  # make sure to indent after function
    i += 1  # add counter

for i in [0, 1, 2]:
    print("meow")

# range useful for large numbers
for i in range(3):
    print("bark")

print("meow\n" * 3, end="")

# How about getting a postive number from user for number of meows0

while True:
    n = int(input("What's n? "))
    if n > 0:
        break

for _ in range(n):
    print("meow")
